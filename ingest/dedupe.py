"""Deduplicación cross-portal / cross-inmobiliaria (F3,
PLAN-radar-inmobiliario.md sección 9).

La misma unidad la publican varias inmobiliarias, a veces en el mismo
portal y a veces en portales distintos, muchas veces a precios distintos.
Sin esto, la mediana de comparables se distorsiona.

Capas de fingerprint, en orden de aplicación:
1. **Dirección normalizada + tipo + ambientes.** Zonaprop y Argenprop
   traen dirección real; Mercado Libre no. Cuando coincide, es la señal
   más confiable — no hace falta foto.
2. **pHash de fotos (Hamming ≤ 6) + m² dentro de ±15% + mismo barrio,
   tipo y ambientes.** La señal para cruzar avisos sin dirección
   coincidente (ej. Mercado Libre contra Zonaprop/Argenprop). Confirmada
   por el plan como "la señal más confiable: las inmobiliarias reusan las
   mismas fotos".

Al unificar, `analysis/latest.py` es quien decide qué precio mostrar
(el más bajo del grupo) — acá solo se calcula el fingerprint. El parquet
crudo nunca pierde filas: cada aviso individual se sigue guardando tal
cual, con su `property_fingerprint` como el dato nuevo.

Costo: comparar todos los pares sería carísimo. Se acota comparando solo
dentro de un balde (barrio, tipo, ambientes), y el pHash de fotos —lo
único que pega a la red— solo se pide para avisos nuevos, con un tope por
corrida (mismo patrón de presupuesto que ingest/snapshot.py ya usa para
el detalle de Mercado Libre), reusando el hash ya calculado en corridas
anteriores (ver `load_known_phashes`).
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx
import imagehash
import pandas as pd
from PIL import Image

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]")


def normalize_address(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = s.lower()
    s = _NON_ALNUM_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip()
    return s or None


class UnionFind:
    """Disjoint-set mínimo: cada aviso arranca siendo su propio grupo."""

    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def fetch_phash(client: httpx.Client, url: str) -> Optional[imagehash.ImageHash]:
    try:
        resp = client.get(url, timeout=10.0)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
        return imagehash.phash(img)
    except Exception:
        return None


def _m2_close(a: Optional[float], b: Optional[float], tolerance: float = 0.15) -> bool:
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(a - b) / max(a, b) <= tolerance


def load_known_phashes(snapshots_dir: Path) -> dict[str, str]:
    """pHash (hex) ya calculado por portal_id, de todos los snapshots
    existentes — para no volver a descargar/hashear la misma foto."""
    known: dict[str, str] = {}
    for path in sorted(snapshots_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "portal_id" not in df.columns or "imagen_phash" not in df.columns:
            continue
        for _, row in df.iterrows():
            h = row.get("imagen_phash")
            if h and isinstance(h, str):
                known[row["portal_id"]] = h
    return known


@dataclass
class DedupeResult:
    fingerprint_by_portal_id: dict[str, str]
    phash_by_portal_id: dict[str, str]  # hex, para persistir en el parquet del día


def find_duplicates(
    rows: list[dict[str, Any]],
    known_phashes: dict[str, str],
    max_new_phash_fetches: int = 500,
    client: Optional[httpx.Client] = None,
) -> DedupeResult:
    uf = UnionFind()
    portal_ids = [r["portal_id"] for r in rows]
    for pid in portal_ids:
        uf.find(pid)

    # Capa 1: dirección normalizada + tipo + ambientes.
    by_addr_key: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        addr = normalize_address(r.get("direccion"))
        if not addr:
            continue
        by_addr_key.setdefault((addr, r.get("tipo"), r.get("ambientes")), []).append(r)
    for group in by_addr_key.values():
        if len(group) < 2:
            continue
        first_id = group[0]["portal_id"]
        for other in group[1:]:
            uf.union(first_id, other["portal_id"])

    # Capa 2: pHash de fotos dentro de un balde (barrio, tipo, ambientes).
    buckets: dict[tuple, list[dict[str, Any]]] = {}
    for r in rows:
        buckets.setdefault((r.get("barrio"), r.get("tipo"), r.get("ambientes")), []).append(r)

    phash_by_portal_id: dict[str, str] = dict(known_phashes)
    new_fetches = 0
    owns_client = client is None
    client = client or httpx.Client()
    try:
        for group in buckets.values():
            if len(group) < 2:
                continue

            hashes: dict[str, imagehash.ImageHash] = {}
            for r in group:
                pid = r["portal_id"]
                cached = phash_by_portal_id.get(pid)
                if cached:
                    try:
                        hashes[pid] = imagehash.hex_to_hash(cached)
                    except ValueError:
                        pass
                    continue
                url = r.get("imagen_url")
                if not url or new_fetches >= max_new_phash_fetches:
                    continue
                h = fetch_phash(client, url)
                new_fetches += 1
                if h is not None:
                    hashes[pid] = h
                    phash_by_portal_id[pid] = str(h)

            items = list(group)
            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    pa, pb = items[i]["portal_id"], items[j]["portal_id"]
                    ha, hb = hashes.get(pa), hashes.get(pb)
                    if ha is None or hb is None:
                        continue
                    if (ha - hb) <= 6 and _m2_close(items[i].get("m2_cubiertos"), items[j].get("m2_cubiertos")):
                        uf.union(pa, pb)
    finally:
        if owns_client:
            client.close()

    groups: dict[str, list[str]] = {}
    for pid in portal_ids:
        groups.setdefault(uf.find(pid), []).append(pid)

    fingerprint_by_portal_id: dict[str, str] = {}
    for members in groups.values():
        fingerprint = f"grp_{min(members)}" if len(members) > 1 else members[0]
        for pid in members:
            fingerprint_by_portal_id[pid] = fingerprint

    return DedupeResult(fingerprint_by_portal_id=fingerprint_by_portal_id, phash_by_portal_id=phash_by_portal_id)
