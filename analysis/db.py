"""Reconstruye un SQLite efímero (data/radar.db, en .gitignore) desde la
secuencia de parquets en data/snapshots/.

Decisión de arquitectura: el parquet es la fuente de verdad; SQLite es un
artefacto derivado que se tira y se reconstruye en cada corrida. Un .db
binario no mergea en git — una secuencia de parquets, uno por día, sí.

F0/F1 solo pueblan `listing` y `listing_snapshot` (ver analysis/schema.sql);
`price_event`, `property` y `cierre_observado` quedan vacías hasta F3/F6.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "radar.db"
DEFAULT_SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def init_db(db_path: Path = DEFAULT_DB_PATH, schema_path: Path = SCHEMA_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)  # reconstrucción desde cero, siempre
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_path.read_text(encoding="utf-8"))
    return conn


def _upsert_listing(conn: sqlite3.Connection, row: dict) -> int:
    conn.execute(
        """
        INSERT INTO listing (portal, portal_id, url, first_seen, last_seen, status)
        VALUES (:portal, :portal_id, :url, :captured_at, :captured_at, :status)
        ON CONFLICT(portal, portal_id) DO UPDATE SET
            last_seen = excluded.last_seen,
            status = excluded.status
        """,
        row,
    )
    cur = conn.execute(
        "SELECT id FROM listing WHERE portal = ? AND portal_id = ?",
        (row["portal"], row["portal_id"]),
    )
    return cur.fetchone()[0]


def _insert_snapshot(conn: sqlite3.Connection, listing_id: int, row: dict) -> None:
    payload = {**row, "listing_id": listing_id}
    conn.execute(
        """
        INSERT OR IGNORE INTO listing_snapshot (
            listing_id, captured_at, price_amount, price_currency, price_usd,
            fx_rate_used, fx_source, fx_fetched_at, expensas_ars, m2_total,
            m2_cubiertos, ambientes, dormitorios, banos, cocheras, antiguedad,
            piso, ascensor, tipo, condicion, barrio, lat, lon, titulo,
            descripcion, es_outlier, outlier_reason, raw_json
        ) VALUES (
            :listing_id, :captured_at, :price_amount, :price_currency, :price_usd,
            :fx_rate_used, :fx_source, :fx_fetched_at, :expensas_ars, :m2_total,
            :m2_cubiertos, :ambientes, :dormitorios, :banos, :cocheras, :antiguedad,
            :piso, :ascensor, :tipo, :condicion, :barrio, :lat, :lon, :titulo,
            :descripcion, :es_outlier, :outlier_reason, :raw_json
        )
        """,
        payload,
    )


def load_dataframe(df: pd.DataFrame, conn: sqlite3.Connection) -> None:
    for _, row in df.iterrows():
        record = row.where(pd.notnull(row), None).to_dict()
        record["status"] = record.get("status") or "active"
        listing_id = _upsert_listing(conn, record)
        _insert_snapshot(conn, listing_id, record)
    conn.commit()


def rebuild_from_snapshots(
    snapshots_dir: Path = DEFAULT_SNAPSHOTS_DIR,
    db_path: Path = DEFAULT_DB_PATH,
    schema_path: Path = SCHEMA_PATH,
) -> sqlite3.Connection:
    conn = init_db(db_path, schema_path)
    for parquet_path in sorted(snapshots_dir.glob("*.parquet")):
        df = pd.read_parquet(parquet_path)
        load_dataframe(df, conn)
    return conn
