"""Orquesta una corrida de ingesta: barrios -> búsqueda ML -> normalización ->
parquet del día.

Deliberadamente simple para F0/F1: sin dedupe (F3), sin valuación (F4),
sin scrapers de Zonaprop/Argenprop (F2). Solo Mercado Libre.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from ingest.fx_mep import get_mep_rate
from ingest.meli_client import MeliClient, extract_listing
from ingest.normalize import normalize_batch

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# TODO(spike): confirmar contra ingest/meli_explore.py.
SEARCH_CATEGORY = "MLA1459"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_barrios(barrios_cfg: dict[str, Any]) -> list[str]:
    nombres: list[str] = []
    for rol in ("nucleo", "propia", "anillo"):
        for entry in barrios_cfg.get(rol, []):
            nombres.append(entry["nombre"])
    return nombres


def fetch_barrio_listings(client: MeliClient, barrio_nombre: str) -> list[dict[str, Any]]:
    params = {"category": SEARCH_CATEGORY, "operation": "sale", "q": barrio_nombre}
    items = list(client.search_all(params))
    return [extract_listing(item, barrio_hint=barrio_nombre) for item in items]


def run_snapshot(
    access_token: str,
    captured_at: str | None = None,
    barrios_cfg_path: Path = CONFIG_DIR / "barrios.yaml",
    costos_cfg_path: Path = CONFIG_DIR / "costos.yaml",
    snapshots_dir: Path = SNAPSHOTS_DIR,
) -> pd.DataFrame:
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc).isoformat()
    fecha = captured_at[:10]

    barrios_cfg = load_yaml(barrios_cfg_path)
    costos_cfg = load_yaml(costos_cfg_path)

    mep = get_mep_rate(price_field=costos_cfg["fx"]["mep_price_field"])

    client = MeliClient(access_token=access_token)
    try:
        raw_records: list[dict[str, Any]] = []
        for barrio in all_barrios(barrios_cfg):
            raw_records.extend(fetch_barrio_listings(client, barrio))
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
