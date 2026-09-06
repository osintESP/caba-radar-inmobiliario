"""Entrypoint del workflow diario (.github/workflows/daily.yml).

Ya no depende de la API/OAuth de Mercado Libre — está bloqueada para apps
no certificadas (confirmado en vivo: `/sites/{site}/search` e `/items/{id}`
devuelven 403 con o sin token). La ingesta scrapea la web pública
(ver ingest/meli_scraper.py). El código OAuth (ingest/meli_auth*.py,
ingest/meli_client.py) queda documentado pero sin uso por ahora.

Orden de pasos, cada uno pensado para fallar RUIDOSAMENTE (excepción con
mensaje claro, exit code != 0) antes que producir un dashboard con datos
viejos o corruptos sin avisar (PLAN-radar-inmobiliario.md, sección 13):

1. Corre la ingesta + normalización del día (ingest/snapshot.py), que ya
   escribe data/snapshots/<fecha>.parquet (sobreescribe si ya corrió hoy).
2. Chequea la tasa de parseo de precio; si cae del 90%, aborta.
3. Reconstruye el SQLite efímero desde todos los parquets (valida que el
   schema completo sigue aplicando limpio).
4. Arma data/latest.json a partir del snapshot del día.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from analysis.db import rebuild_from_snapshots
from analysis.latest import build_latest_json
from ingest.normalize import check_parse_rate
from ingest.snapshot import run_snapshot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LATEST_JSON_PATH = DATA_DIR / "latest.json"


def main() -> int:
    df = run_snapshot()

    if df.empty:
        raise RuntimeError("La corrida de hoy no trajo ningún aviso — abortando antes de sobreescribir latest.json.")

    check_parse_rate(df.to_dict(orient="records"), field="price_usd", min_rate=0.9)

    rebuild_from_snapshots()  # valida que el schema completo sigue aplicando limpio

    latest = build_latest_json(df)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"OK: {latest['n_avisos']} avisos publicados de {latest['n_avisos_total']} obtenidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
