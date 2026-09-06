-- Schema completo de PLAN-radar-inmobiliario.md, sección 6.
-- F0/F1 solo pueblan `listing` y `listing_snapshot`; el resto queda definido
-- desde ya para que las fases futuras (dedupe, valuación, brecha neta, carga
-- de cierres) no requieran migraciones.
--
-- Este archivo se aplica sobre un SQLite EFÍMERO (data/radar.db, en .gitignore).
-- La fuente de verdad es la secuencia de parquets en data/snapshots/: este .db
-- se reconstruye desde cero en cada corrida (ver analysis/db.py).

CREATE TABLE listing (
  id INTEGER PRIMARY KEY,
  portal TEXT NOT NULL,              -- 'zonaprop'|'argenprop'|'meli'
  portal_id TEXT NOT NULL,
  url TEXT NOT NULL,
  property_id INTEGER,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL,
  status TEXT NOT NULL,              -- 'active'|'gone'|'paused'|'closed'
  gone_at TEXT,
  UNIQUE(portal, portal_id)
);

CREATE TABLE listing_snapshot (
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listing(id),
  captured_at TEXT NOT NULL,
  price_amount REAL, price_currency TEXT,
  price_usd REAL, fx_rate_used REAL,
  fx_source TEXT,                    -- 'dolarapi:bolsa'|'criptoya:mep' — desviación
  fx_fetched_at TEXT,                -- documentada respecto a la sección 6 del doc:
                                      -- trazabilidad de la cotización usada por fila.
  expensas_ars REAL,
  m2_total REAL, m2_cubiertos REAL,
  ambientes INTEGER, dormitorios INTEGER, banos INTEGER, cocheras INTEGER,
  antiguedad INTEGER, piso INTEGER, ascensor INTEGER,
  tipo TEXT, condicion TEXT,
  barrio TEXT, lat REAL, lon REAL,
  titulo TEXT, descripcion TEXT,
  es_outlier INTEGER NOT NULL DEFAULT 0,
  outlier_reason TEXT,
  raw_json TEXT,
  -- Permite reconstruir sin duplicar si el job corre dos veces el mismo día UTC
  -- (mismo razonamiento que la idempotencia por nombre de archivo del parquet).
  UNIQUE(listing_id, captured_at)
);

CREATE TABLE price_event (       -- F6, no poblada en F0/F1
  id INTEGER PRIMARY KEY,
  listing_id INTEGER NOT NULL REFERENCES listing(id),
  event_at TEXT NOT NULL,
  event_type TEXT NOT NULL,          -- 'listed'|'price_change'|'delisted'|'relisted'
  old_price_usd REAL, new_price_usd REAL, pct_change REAL
);

CREATE TABLE property (          -- F3+ (dedupe), no poblada en F0/F1
  id INTEGER PRIMARY KEY,
  fingerprint TEXT UNIQUE,
  barrio TEXT, lat REAL, lon REAL,
  m2_total REAL, ambientes INTEGER, tipo TEXT
);

CREATE TABLE cierre_observado (  -- F6 (carga de cierres), no poblada en F0/F1
  id INTEGER PRIMARY KEY,
  fecha TEXT NOT NULL,
  barrio TEXT, direccion_aprox TEXT,
  tipo TEXT, ambientes INTEGER, m2 REAL,
  precio_publicado_usd REAL,
  precio_cierre_usd REAL NOT NULL,
  fuente TEXT,                       -- quién lo reportó
  confianza TEXT                     -- 'alta'|'media'|'baja'
);
