"""Detección de eventos de precio sobre los avisos (base de F6,
PLAN-radar-inmobiliario.md sección 3.2, fuente A4: "la única fuente
hiperlocal automatizada" de señal de cierre real).

Dos tipos de evento, ambos comparando el snapshot de HOY contra el más
reciente anterior (no contra todo el histórico: interesa el cambio más
reciente, no re-detectar el mismo hueco/recorte todos los días):

- `delisted`: el aviso estaba activo ayer y hoy no aparece. Lo más
  probable es que se haya reservado, vendido, o dado de baja por otro
  motivo — no sabemos CUÁL (eso requiere A5: preguntarle al corredor),
  pero la desaparición en sí es una señal real y gratuita.
- `price_change`: el aviso sigue activo pero su `price_usd` cambió.
  Recorte o suba — el signo de `pct_change` distingue uno de otro. Es
  el dato que le falta a "brecha neta" (F5): separar el recorte que el
  aviso YA hizo del margen que le queda (sección 3.1 del plan).

El resultado se ACUMULA en `data/price_events.parquet` — mismo criterio
que `data/snapshots/`: nunca se borra nada, cada corrida solo agrega
filas nuevas.

Deliberadamente simple para esta primera versión: "relisted" (reapareció
después de haber desaparecido) queda para una iteración futura.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

EVENTS_COLUMNS = [
    "portal",
    "portal_id",
    "event_type",  # 'delisted' | 'price_change'
    "event_at",
    "barrio",
    "tipo",
    "price_usd",
    "old_price_usd",  # solo 'price_change'
    "new_price_usd",  # solo 'price_change'
    "pct_change",  # solo 'price_change'
    "url",
    "titulo",
]


def _previous_snapshot_path(snapshots_dir: Path, current_path: Path) -> Optional[Path]:
    files = sorted(p for p in snapshots_dir.glob("*.parquet") if p.name != current_path.name)
    return files[-1] if files else None


def detect_delistings(current_df: pd.DataFrame, snapshots_dir: Path, current_path: Path, event_at: str) -> pd.DataFrame:
    """Avisos presentes en el snapshot anterior que no están en `current_df`."""
    previous_path = _previous_snapshot_path(snapshots_dir, current_path)
    if previous_path is None:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    previous_df = pd.read_parquet(previous_path)
    if "portal_id" not in previous_df.columns or previous_df.empty:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    current_ids = set(current_df["portal_id"]) if not current_df.empty else set()
    gone = previous_df[~previous_df["portal_id"].isin(current_ids)]
    if gone.empty:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    events = gone[["portal", "portal_id", "barrio", "tipo", "price_usd", "url", "titulo"]].copy()
    events["event_type"] = "delisted"
    events["event_at"] = event_at
    events["old_price_usd"] = None
    events["new_price_usd"] = None
    events["pct_change"] = None
    return events[EVENTS_COLUMNS]


def detect_price_changes(current_df: pd.DataFrame, snapshots_dir: Path, current_path: Path, event_at: str) -> pd.DataFrame:
    """Avisos presentes en ambos snapshots (hoy y el anterior) cuyo
    `price_usd` cambió."""
    previous_path = _previous_snapshot_path(snapshots_dir, current_path)
    if previous_path is None or current_df.empty:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    previous_df = pd.read_parquet(previous_path)
    if "portal_id" not in previous_df.columns or previous_df.empty:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    merged = current_df[["portal", "portal_id", "barrio", "tipo", "price_usd", "url", "titulo"]].merge(
        previous_df[["portal_id", "price_usd"]].rename(columns={"price_usd": "old_price_usd"}),
        on="portal_id",
        how="inner",
    )
    changed = merged[
        merged["price_usd"].notna() & merged["old_price_usd"].notna() & (merged["price_usd"] != merged["old_price_usd"])
    ].copy()
    if changed.empty:
        return pd.DataFrame(columns=EVENTS_COLUMNS)

    changed["new_price_usd"] = changed["price_usd"]
    changed["pct_change"] = (changed["new_price_usd"] - changed["old_price_usd"]) / changed["old_price_usd"] * 100
    changed["event_type"] = "price_change"
    changed["event_at"] = event_at
    return changed[EVENTS_COLUMNS]


def append_events(events_df: pd.DataFrame, events_path: Path) -> pd.DataFrame:
    """Agrega `events_df` al log acumulado en `events_path` (nunca reemplaza
    lo que ya había) y devuelve el log completo actualizado."""
    if events_path.exists():
        existing = pd.read_parquet(events_path)
        combined = pd.concat([existing, events_df], ignore_index=True)
    else:
        combined = events_df

    if not combined.empty:
        # Por si la misma corrida se ejecuta dos veces el mismo día
        # (idempotencia, mismo criterio que data/snapshots/).
        combined = combined.drop_duplicates(subset=["portal_id", "event_type", "event_at"], keep="last")

    events_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(events_path, index=False)
    return combined
