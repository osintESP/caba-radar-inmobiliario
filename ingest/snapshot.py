"""Orquesta una corrida de ingesta: barrios -> scraping de los 3 portales ->
normalización -> parquet del día.

Sin dedupe todavía (F3) ni valuación (F4). F2 (Zonaprop/Argenprop) recién
se agrega en esta sesión — activable/desactivable por separado en
`config/barrios.yaml: fuentes`, porque a diferencia de Mercado Libre estos
dos portales necesitan un navegador real (ver ingest/browser_utils.py) y
todavía no está confirmado que eso funcione desde un runner de GitHub
Actions (IP de datacenter) y no solo desde una máquina local — ver
README.md.

Dos diseños de costo bien distintos conviven acá:

- **Mercado Libre**: la página de LISTADO es barata (1 request cada 48
  avisos) pero NO trae m²/ambientes — eso exige visitar el DETALLE de cada
  aviso (1 request por aviso). Con barrios de alto volumen, pedir el
  detalle de todos el mismo día no es sostenible, así que solo se pide
  para avisos NUEVOS, con un tope diario repartido parejo entre barrio x
  tipología (`scraping.max_new_detail_fetches_por_corrida`). Los avisos ya
  conocidos heredan sus atributos de detalle (no cambian) de la última vez
  que se los vio.
- **Zonaprop/Argenprop**: la página de LISTADO ya trae casi todo (precio,
  m², ambientes, dirección) — no hace falta visitar el detalle de cada
  aviso. Se recorren todas las páginas de resultados todos los días, sin
  cupo ni caché de "conocidos".
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from ingest import argenprop_scraper, dedupe, meli_scraper, zonaprop_scraper
from ingest.browser_utils import browser_session
from ingest.fx_mep import get_mep_rate
from ingest.normalize import normalize_batch

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

DETAIL_FIELDS = [
    "m2_total",
    "m2_cubiertos",
    "ambientes",
    "dormitorios",
    "banos",
    "cocheras",
    "antiguedad",
    "piso",
    "ascensor",
    "expensas_ars",
    "condicion",
]


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_barrios(barrios_cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Devuelve [(nombre, meli_slug), ...] para nucleo + propia + anillo."""
    out: list[tuple[str, str]] = []
    for rol in ("nucleo", "propia", "anillo"):
        for entry in barrios_cfg.get(rol, []):
            out.append((entry["nombre"], entry["meli_slug"]))
    return out


def load_known_attributes(snapshots_dir: Path) -> dict[str, dict[str, Any]]:
    """Últimos atributos de DETALLE conocidos por portal_id, de todos los
    snapshots existentes. Un portal_id solo se considera "conocido" si en
    algún momento se le pudo pedir el detalle (si nunca se enriqueció por
    haber tocado el tope diario, sigue "no conocido" y se reintenta)."""
    known: dict[str, dict[str, Any]] = {}
    for path in sorted(snapshots_dir.glob("*.parquet")):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "portal_id" not in df.columns:
            continue
        for _, row in df.iterrows():
            if pd.isna(row.get("ambientes")) and pd.isna(row.get("m2_cubiertos")):
                continue  # nunca se enriqueció este aviso; se reintenta
            known[row["portal_id"]] = {field: row.get(field) for field in DETAIL_FIELDS}
    return known


def _scrape_browser_portal(
    scraper_module: Any,
    browser: Any,
    barrios_cfg: dict[str, Any],
    max_pages: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Recorre barrio x tipología con un scraper basado en Playwright
    (Zonaprop o Argenprop, mismo contrato: search_barrio_tipo(browser,
    nombre, slug, tipo, max_pages=...)). `max_pages` sirve para acotar una
    corrida de prueba (ver README, verificación de viabilidad en GitHub
    Actions)."""
    records: list[dict[str, Any]] = []
    for barrio_nombre, barrio_slug in all_barrios(barrios_cfg):
        for tipo in barrios_cfg["tipologias"]:
            records.extend(
                scraper_module.search_barrio_tipo(browser, barrio_nombre, barrio_slug, tipo, max_pages=max_pages)
            )
    return records


def run_snapshot(
    captured_at: Optional[str] = None,
    barrios_cfg_path: Path = CONFIG_DIR / "barrios.yaml",
    costos_cfg_path: Path = CONFIG_DIR / "costos.yaml",
    snapshots_dir: Path = SNAPSHOTS_DIR,
) -> pd.DataFrame:
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc).isoformat()
    fecha = captured_at[:10]

    barrios_cfg = load_yaml(barrios_cfg_path)
    costos_cfg = load_yaml(costos_cfg_path)

    mep = get_mep_rate(price_field=costos_cfg["fx"]["mep_price_field"])

    fuentes = barrios_cfg.get("fuentes", {})
    raw_records: list[dict[str, Any]] = []

    if fuentes.get("meli", True):
        known = load_known_attributes(snapshots_dir)
        max_new_fetches = barrios_cfg.get("scraping", {}).get("max_new_detail_fetches_por_corrida", 250)

        combos = [
            (barrio_nombre, barrio_slug, tipo)
            for barrio_nombre, barrio_slug in all_barrios(barrios_cfg)
            for tipo in barrios_cfg["tipologias"]
        ]
        # Cupo PAREJO por combinación barrio x tipología. Sin esto, un barrio
        # de alto volumen (ej. Flores) agota el cupo global entero y deja a
        # los demás —incluida "propia", donde está la propiedad a vender— en
        # cero el mismo día (pasó exactamente esto en la primera corrida
        # real). El resto que sobra después de darle su piso a cada combo se
        # reparte en orden de aparición (núcleo/propia primero, ver
        # all_barrios), no round-robin, porque ese orden ya refleja la
        # prioridad del plan.
        per_combo_cap = max(1, max_new_fetches // len(combos)) if combos else 0
        new_fetches = 0

        client = meli_scraper.make_client()
        pending_new: list[dict[str, Any]] = []  # avisos nuevos que no llegaron a enriquecerse en el primer paso
        try:
            for barrio_nombre, barrio_slug, tipo in combos:
                combo_new_fetches = 0
                for summary in meli_scraper.search_barrio_tipo(client, barrio_nombre, barrio_slug, tipo):
                    record = dict(summary)
                    portal_id = record["portal_id"]

                    if portal_id in known:
                        record.update(known[portal_id])
                    elif combo_new_fetches < per_combo_cap and new_fetches < max_new_fetches:
                        detail = meli_scraper.fetch_detail(client, record["url"])
                        record.update(detail)
                        combo_new_fetches += 1
                        new_fetches += 1
                    else:
                        pending_new.append(record)  # candidato para el cupo sobrante

                    raw_records.append(record)

            # Segundo paso: lo que sobró del cupo global (porque algún combo
            # tenía menos avisos nuevos que su piso) se reparte entre los
            # avisos que quedaron pendientes, en el mismo orden de prioridad.
            for record in pending_new:
                if new_fetches >= max_new_fetches:
                    break
                detail = meli_scraper.fetch_detail(client, record["url"])
                record.update(detail)
                new_fetches += 1
        finally:
            client.close()

    if fuentes.get("zonaprop", True) or fuentes.get("argenprop", True):
        with browser_session() as browser:
            if fuentes.get("zonaprop", True):
                raw_records.extend(_scrape_browser_portal(zonaprop_scraper, browser, barrios_cfg))
            if fuentes.get("argenprop", True):
                raw_records.extend(_scrape_browser_portal(argenprop_scraper, browser, barrios_cfg))

    for record in raw_records:
        record["raw_json"] = json.dumps(
            {f: record.get(f) for f in ["portal_id", "url", "price_amount", "price_currency", *DETAIL_FIELDS]},
            ensure_ascii=False,
        )

    outliers_cfg = barrios_cfg.get("outliers", {})
    rows = normalize_batch(
        raw_records,
        mep=mep,
        usd_m2_min=outliers_cfg.get("usd_m2_min", 400),
        usd_m2_max=outliers_cfg.get("usd_m2_max", 8000),
        captured_at=captured_at,
    )

    # F3: dedupe cross-portal/cross-inmobiliaria (ver ingest/dedupe.py). El
    # pHash de fotos es lo único que pega a la red acá, así que también
    # tiene un tope diario, reusando el hash ya calculado en corridas
    # anteriores para no volver a descargar la misma imagen.
    max_new_phash = barrios_cfg.get("scraping", {}).get("max_new_phash_fetches_por_corrida", 500)
    known_phashes = dedupe.load_known_phashes(snapshots_dir)
    dedupe_result = dedupe.find_duplicates(rows, known_phashes, max_new_phash_fetches=max_new_phash)
    for row in rows:
        pid = row["portal_id"]
        row["property_fingerprint"] = dedupe_result.fingerprint_by_portal_id.get(pid, pid)
        row["imagen_phash"] = dedupe_result.phash_by_portal_id.get(pid)

    df = pd.DataFrame(rows)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir / f"{fecha}.parquet"
    df.to_parquet(out_path, index=False)  # sobreescribe si ya existía (idempotente por nombre)

    return df
