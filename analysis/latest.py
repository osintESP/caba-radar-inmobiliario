"""Arma data/latest.json a partir del DataFrame normalizado del día.

Sale directo del snapshot del día, no de SQLite: F1 (mostrar la tabla) no
depende de que la reconstrucción de analysis/db.py ande perfecta.

Filas outlier o sin precio se excluyen de la vista del sitio pero no se
borran de nada — siguen en el parquet completo.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd

DISPLAY_COLUMNS = [
    "barrio",
    "tipo",
    "condicion",
    "ambientes",
    "m2_cubiertos",
    "price_usd",
    "usd_m2",
    "expensas_ars",
    "antiguedad",
    "piso",
    "ascensor",
    "url",
    "captured_at",
]


def build_latest_json(df: pd.DataFrame) -> dict[str, Any]:
    fx_rate = float(df["fx_rate_used"].iloc[0]) if not df.empty and "fx_rate_used" in df else None
    fx_source = str(df["fx_source"].iloc[0]) if not df.empty and "fx_source" in df else None

    visible = df
    if not df.empty:
        visible = df[(~df["es_outlier"].fillna(False)) & df["price_usd"].notna()]

    records = visible[DISPLAY_COLUMNS].where(pd.notnull(visible[DISPLAY_COLUMNS]), None).to_dict(orient="records") if not visible.empty else []

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fx_rate": fx_rate,
        "fx_source": fx_source,
        "n_avisos": len(records),
        "n_avisos_total": int(len(df)),
        "avisos": records,
    }
