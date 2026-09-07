"""Arma data/latest.json a partir del DataFrame normalizado del día.

Sale directo del snapshot del día, no de SQLite: F1 (mostrar la tabla) no
depende de que la reconstrucción de analysis/db.py ande perfecta.

Filas outlier o sin precio se excluyen de la vista del sitio pero no se
borran de nada — siguen en el parquet completo.
"""

from __future__ import annotations

import datetime as dt
import math
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

    records = []
    if not visible.empty:
        for record in visible[DISPLAY_COLUMNS].to_dict(orient="records"):
            # pandas castea None de vuelta a NaN en columnas float (no puede
            # guardar None en un float64) — json.dumps() serializaría eso
            # como el literal `NaN`, que es JSON inválido y rompe
            # JSON.parse() en el navegador. Se reemplaza acá, después de
            # pasar por dict, donde ya no hay dtype de columna que fuerce
            # el cast de vuelta.
            records.append(
                {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in record.items()}
            )

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fx_rate": fx_rate,
        "fx_source": fx_source,
        "n_avisos": len(records),
        "n_avisos_total": int(len(df)),
        "avisos": records,
    }
