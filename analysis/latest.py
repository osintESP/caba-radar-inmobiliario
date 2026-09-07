"""Arma data/latest.json a partir del DataFrame normalizado del día.

Sale directo del snapshot del día, no de SQLite: F1 (mostrar la tabla) no
depende de que la reconstrucción de analysis/db.py ande perfecta.

Filas outlier, sin precio, o duplicadas de otra ya mostrada (mismo
`property_fingerprint`, ver ingest/dedupe.py — F3) se excluyen de la vista
del sitio pero no se borran de nada, siguen en el parquet completo. De
cada grupo de duplicados se muestra solo la de menor precio
(PLAN-radar-inmobiliario.md, sección 9: "al unificar, conservar el precio
más bajo"), con `n_duplicados` indicando cuántos avisos representa.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd

DISPLAY_COLUMNS = [
    "portal",
    "barrio",
    "tipo",
    "condicion",
    "ambientes",
    "banos",
    "cocheras",
    "m2_cubiertos",
    "price_usd",
    "usd_m2",
    "expensas_ars",
    "antiguedad",
    "piso",
    "ascensor",
    "url",
    "captured_at",
    "n_duplicados",
]


def build_latest_json(df: pd.DataFrame) -> dict[str, Any]:
    fx_rate = float(df["fx_rate_used"].iloc[0]) if not df.empty and "fx_rate_used" in df else None
    fx_source = str(df["fx_source"].iloc[0]) if not df.empty and "fx_source" in df else None

    visible = df
    if not df.empty:
        visible = df[(~df["es_outlier"].fillna(False)) & df["price_usd"].notna()]

    if not visible.empty and "property_fingerprint" in visible.columns:
        visible = visible.assign(
            n_duplicados=visible.groupby("property_fingerprint")["portal_id"].transform("count")
        )
        # Un aviso por grupo de duplicados: el de menor precio. El resto
        # del grupo sigue en el parquet, no se borra nada.
        visible = visible.sort_values("price_usd").drop_duplicates(subset="property_fingerprint", keep="first")
    elif not visible.empty:
        visible = visible.assign(n_duplicados=1)

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
