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
    "portal_id",
    "titulo",
    "barrio",
    "tipo",
    "condicion",
    "ambientes",
    "banos",
    "cocheras",
    "m2_cubiertos",
    "price_usd",
    "usd_m2",
    "usd_m2_mediana_zona",
    "percentil_zona",
    "n_comparables_zona",
    "veredicto_zona",
    "brecha_neta_usd",
    "brecha_neta_papa_usd",
    "pct_negociacion_estimado",
    "expensas_ars",
    "antiguedad",
    "piso",
    "ascensor",
    "url",
    "imagen_url",
    "captured_at",
    "n_duplicados",
    "es_nuevo",
    "tags",
]


def deduplicated_view(df: pd.DataFrame) -> pd.DataFrame:
    """Un aviso por grupo de duplicados (`property_fingerprint`, ver
    ingest/dedupe.py): el de menor precio, con `n_duplicados` indicando
    cuántos avisos representa. El resto del grupo no se borra de `df`,
    esto es solo una vista derivada — la usan tanto el sitio
    (`build_latest_json`) como el motor de valuación (F4), para no dejar
    que la misma unidad publicada por varias inmobiliarias pese varias
    veces en una mediana."""
    if df.empty:
        return df
    if "property_fingerprint" not in df.columns:
        return df.assign(n_duplicados=1)

    view = df.assign(n_duplicados=df.groupby("property_fingerprint")["portal_id"].transform("count"))
    return view.sort_values("price_usd").drop_duplicates(subset="property_fingerprint", keep="first")


def _https(url: Any) -> str | None:
    """Mercado Libre devuelve las fotos como `http://http2.mlstatic.com/...`
    (el mismo host sirve https). El sitio va por https (GitHub Pages) y el
    navegador bloquea o degrada imágenes http como contenido mixto."""
    if not isinstance(url, str) or not url:
        return None
    return "https://" + url[len("http://"):] if url.startswith("http://") else url


def build_latest_json(df: pd.DataFrame) -> dict[str, Any]:
    fx_rate = float(df["fx_rate_used"].iloc[0]) if not df.empty and "fx_rate_used" in df else None
    fx_source = str(df["fx_source"].iloc[0]) if not df.empty and "fx_source" in df else None

    visible = df
    if not df.empty:
        # zona_externa (config/barrios.yaml: externas, ej. Merlo): alimenta
        # comparables para auditar la propiedad puntual de otro perfil
        # (ver ingest/run_daily.py::_audit_mi_propiedad), nunca es candidata
        # de compra — no pertenece a la tabla del sitio. Ausente en
        # snapshots viejos (anteriores a esta columna): se asume False.
        es_zona_externa = (
            df["zona_externa"].fillna(False) if "zona_externa" in df.columns else pd.Series(False, index=df.index)
        )
        fuera = df["fuera_de_perimetro"].fillna(False) if "fuera_de_perimetro" in df.columns else pd.Series(False, index=df.index)
        visible = df[(~df["es_outlier"].fillna(False)) & df["price_usd"].notna() & (~es_zona_externa) & (~fuera)]

    visible = deduplicated_view(visible)

    records = []
    if not visible.empty:
        # Tolerante a columnas nuevas ausentes en un DataFrame más viejo
        # (ej. si algún día se lee un snapshot de antes de que existiera
        # "tags"/"es_nuevo"): se agregan como None en vez de romper. En la
        # corrida diaria normal esto nunca hace falta — run_snapshot()
        # siempre las genera todas — pero abarata reprocesar histórico.
        display_view = visible.reindex(columns=DISPLAY_COLUMNS)
        for record in display_view.to_dict(orient="records"):
            # pandas castea None de vuelta a NaN en columnas float (no puede
            # guardar None en un float64) — json.dumps() serializaría eso
            # como el literal `NaN`, que es JSON inválido y rompe
            # JSON.parse() en el navegador. Se reemplaza acá, después de
            # pasar por dict, donde ya no hay dtype de columna que fuerce
            # el cast de vuelta.
            clean = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in record.items()}
            clean["imagen_url"] = _https(clean.get("imagen_url"))
            records.append(clean)

    return {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fx_rate": fx_rate,
        "fx_source": fx_source,
        "n_avisos": len(records),
        "n_avisos_total": int(len(df)),
        "avisos": records,
    }
