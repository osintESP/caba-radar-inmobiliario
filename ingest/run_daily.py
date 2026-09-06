"""Entrypoint del workflow diario (.github/workflows/daily.yml).

Orden de pasos, cada uno pensado para fallar RUIDOSAMENTE (excepción con
mensaje claro, exit code != 0) antes que producir un dashboard con datos
viejos o corruptos sin avisar (PLAN-radar-inmobiliario.md, sección 13):

1. Refresca el access_token de Mercado Libre. Si ML rotó el refresh_token,
   lo actualiza en GitHub Secrets.
2. Corre la ingesta + normalización del día (ingest/snapshot.py), que ya
   escribe data/snapshots/<fecha>.parquet (sobreescribe si ya corrió hoy).
3. Chequea la tasa de parseo de precio; si cae del 90%, aborta.
4. Reconstruye el SQLite efímero desde todos los parquets (valida que el
   schema completo sigue aplicando limpio).
5. Arma data/latest.json a partir del snapshot del día.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from analysis.db import rebuild_from_snapshots
from analysis.latest import build_latest_json
from ingest.gh_secrets import set_secret
from ingest.meli_auth import refresh_access_token
from ingest.normalize import check_parse_rate
from ingest.snapshot import run_snapshot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LATEST_JSON_PATH = DATA_DIR / "latest.json"

REQUIRED_ENV = ["ML_CLIENT_ID", "ML_CLIENT_SECRET", "ML_REFRESH_TOKEN"]


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name}.")
    return value


def _refresh_ml_token() -> str:
    client_id = _require_env("ML_CLIENT_ID")
    client_secret = _require_env("ML_CLIENT_SECRET")
    old_refresh_token = _require_env("ML_REFRESH_TOKEN")

    try:
        tokens = refresh_access_token(client_id, client_secret, old_refresh_token)
    except Exception as exc:  # noqa: BLE001 — se re-levanta con contexto accionable
        raise RuntimeError(
            "No se pudo refrescar el access_token de Mercado Libre. Si el "
            "refresh_token fue revocado o expiró, correr de nuevo "
            "`uv run python -m ingest.meli_auth_bootstrap` para reautorizar. "
            f"Error original: {exc}"
        ) from exc

    if tokens.refresh_token != old_refresh_token:
        repo = os.environ.get("GITHUB_REPOSITORY")
        pat = os.environ.get("GH_SECRETS_PAT")
        if not pat:
            raise RuntimeError(
                "Mercado Libre rotó el refresh_token pero falta el secret "
                "GH_SECRETS_PAT para persistir el nuevo valor. Sin esto, la "
                "próxima corrida va a fallar al refrescar."
            )
        set_secret("ML_REFRESH_TOKEN", tokens.refresh_token, repo=repo, token=pat)

    return tokens.access_token


def main() -> int:
    access_token = _refresh_ml_token()

    df = run_snapshot(access_token=access_token)

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
