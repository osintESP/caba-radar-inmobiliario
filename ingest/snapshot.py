"""Orquesta una corrida de ingesta: barrios -> scraping de ML -> normalización
-> parquet del día.

Deliberadamente simple para F0/F1: sin dedupe (F3), sin valuación (F4),
sin scrapers de Zonaprop/Argenprop (F2). Solo Mercado Libre, vía la web
pública (ver ingest/meli_scraper.py — la API oficial está bloqueada para
apps no certificadas, confirmado en vivo).

Diseño clave: la página de LISTADO es barata (1 request cada 48 avisos) y
se recorre completa todos los días para todo barrio x tipología. La página
de DETALLE de cada aviso es cara (1 request por aviso) y solo se pide para
avisos NUEVOS (no vistos en corridas anteriores), con un tope diario
(`config/barrios.yaml: scraping.max_new_detail_fetches_por_corrida`) — con
barrios de alto volumen, pedir el detalle de todos el mismo día no es
sostenible ni cortés. Los avisos ya conocidos heredan sus atributos de
detalle (m², ambientes, etc. — no cambian) de la última vez que se los
vio; los que no llegaron a enriquecerse hoy quedan con esos campos en
NULL (nunca imputados) y se reintentan en una corrida futura.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from ingest import meli_scraper
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

    known = load_known_attributes(snapshots_dir)
    max_new_fetches = barrios_cfg.get("scraping", {}).get("max_new_detail_fetches_por_corrida", 250)
    new_fetches = 0

    client = meli_scraper.make_client()
    raw_records: list[dict[str, Any]] = []
    try:
        for barrio_nombre, barrio_slug in all_barrios(barrios_cfg):
            for tipo in barrios_cfg["tipologias"]:
                for summary in meli_scraper.search_barrio_tipo(client, barrio_nombre, barrio_slug, tipo):
                    record = dict(summary)
                    portal_id = record["portal_id"]

                    if portal_id in known:
                        record.update(known[portal_id])
                    elif new_fetches < max_new_fetches:
                        detail = meli_scraper.fetch_detail(client, record["url"])
                        record.update(detail)
                        new_fetches += 1
                    # si no, el aviso queda sin atributos de detalle por hoy
                    # (None, nunca imputado) y se reintenta mañana.

                    record["raw_json"] = json.dumps(
                        {**summary, **{f: record.get(f) for f in DETAIL_FIELDS}}, ensure_ascii=False
                    )
                    raw_records.append(record)
    finally:
        client.close()

    outliers_cfg = barrios_cfg.get("outliers", {})
    rows = normalize_batch(
        raw_records,
        mep=mep,
        usd_m2_min=outliers_cfg.get("usd_m2_min", 400),
        usd_m2_max=outliers_cfg.get("usd_m2_max", 8000),
        captured_at=captured_at,
    )

    df = pd.DataFrame(rows)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    out_path = snapshots_dir / f"{fecha}.parquet"
    df.to_parquet(out_path, index=False)  # sobreescribe si ya existía (idempotente por nombre)

    return df
