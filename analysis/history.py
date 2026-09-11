"""Historial multi-día — ficha de propiedad y Vista de Mercado (F6,
PLAN-radar-inmobiliario.md sección 11: "el gráfico que ningún portal
muestra" y "evolución de USD/m² por barrio").

Recorre todos los snapshots diarios acumulados en `data/snapshots/`
(nunca se borran, ver `ingest/snapshot.py`) para armar dos series
compactas:

- Por aviso (`build_price_history`): la serie de precio en el tiempo.
- Por barrio (`build_market_trends`): la mediana de USD/m² día a día.

Separado de `data/latest.json` (que solo tiene el snapshot de hoy) para
no inflar el payload que carga la tabla principal — estos JSON se cargan
recién cuando el usuario abre una ficha o la vista de Mercado.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

_SNAPSHOT_COLUMNS = ["portal", "portal_id", "barrio", "usd_m2", "price_usd", "es_outlier"]


def _load_all_snapshots(snapshots_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(snapshots_dir.glob("*.parquet")):
        snapshot = pd.read_parquet(path, columns=_SNAPSHOT_COLUMNS)
        snapshot["fecha"] = path.stem
        frames.append(snapshot)
    if not frames:
        return pd.DataFrame(columns=[*_SNAPSHOT_COLUMNS, "fecha"])
    return pd.concat(frames, ignore_index=True)


def build_price_history(snapshots_dir: Path) -> dict[str, list[dict]]:
    """`{"portal:portal_id": [{"fecha": ..., "price_usd": ...}, ...]}`,
    ordenado por fecha, solo con los días en que el aviso tuvo precio."""
    all_snapshots = _load_all_snapshots(snapshots_dir)
    con_precio = all_snapshots[all_snapshots["price_usd"].notna()].copy()
    if con_precio.empty:
        return {}
    con_precio["clave"] = con_precio["portal"] + ":" + con_precio["portal_id"]

    historial: dict[str, list[dict]] = {}
    for clave, grupo in con_precio.sort_values("fecha").groupby("clave"):
        historial[clave] = grupo[["fecha", "price_usd"]].to_dict(orient="records")
    return historial


def build_market_trends(snapshots_dir: Path) -> dict[str, list[dict]]:
    """`{"Barrio": [{"fecha": ..., "mediana_usd_m2": ..., "n_avisos": ...}, ...]}`."""
    all_snapshots = _load_all_snapshots(snapshots_dir)
    validos = all_snapshots[(~all_snapshots["es_outlier"].fillna(False)) & all_snapshots["usd_m2"].notna()]
    if validos.empty:
        return {}

    tendencias: dict[str, list[dict]] = {}
    for (barrio, fecha), grupo in validos.groupby(["barrio", "fecha"]):
        tendencias.setdefault(barrio, []).append(
            {
                "fecha": fecha,
                "mediana_usd_m2": float(grupo["usd_m2"].median()),
                "n_avisos": int(len(grupo)),
            }
        )
    for series in tendencias.values():
        series.sort(key=lambda fila: fila["fecha"])
    return tendencias
