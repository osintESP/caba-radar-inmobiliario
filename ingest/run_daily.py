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
5. Audita "mi propiedad" contra comparables reales (F4, sección 10) con
   EXACTAMENTE el mismo motor que cualquier candidata — sin rama especial.
6. Detecta avisos que desaparecieron desde el snapshot anterior (base de
   F6, ingest/price_events.py) y los acumula en data/price_events.parquet.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from analysis.db import rebuild_from_snapshots
from analysis.latest import build_latest_json, deduplicated_view
from analysis.valuation import audit_property
from ingest.normalize import check_parse_rate
from ingest.price_events import append_events, detect_delistings
from ingest.snapshot import CONFIG_DIR, SNAPSHOTS_DIR, load_yaml, run_snapshot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LATEST_JSON_PATH = DATA_DIR / "latest.json"
PRICE_EVENTS_PATH = DATA_DIR / "price_events.parquet"


def _audit_mi_propiedad(df) -> dict:
    mi_propiedad = load_yaml(CONFIG_DIR / "mi_propiedad.yaml")["mi_propiedad"]
    adyacentes = load_yaml(CONFIG_DIR / "barrios.yaml").get("adyacentes", {})

    comparables_pool = deduplicated_view(df[(~df["es_outlier"].fillna(False)) & df["price_usd"].notna()])
    usd_m2_declarado = mi_propiedad["precio_venta_max_usd"] / mi_propiedad["m2_cubiertos"]

    auditoria = audit_property(
        comparables_pool,
        barrio=mi_propiedad["barrio"],
        tipo=mi_propiedad["tipo"],
        ambientes=mi_propiedad["ambientes"],
        m2_cubiertos=mi_propiedad["m2_cubiertos"],
        adyacentes=adyacentes,
        usd_m2_sujeto=usd_m2_declarado,
    )
    return {
        "barrio": mi_propiedad["barrio"],
        "tipo": mi_propiedad["tipo"],
        "ambientes": mi_propiedad["ambientes"],
        "m2_cubiertos": mi_propiedad["m2_cubiertos"],
        "precio_venta_max_usd": mi_propiedad["precio_venta_max_usd"],
        "usd_m2_declarado": usd_m2_declarado,
        "n_comparables": auditoria.n_comparables,
        "scope": auditoria.scope,
        "usd_m2_mediana": auditoria.usd_m2_mediana,
        "usd_m2_p25": auditoria.usd_m2_p25,
        "usd_m2_p75": auditoria.usd_m2_p75,
        "percentil_sujeto": auditoria.percentil_sujeto,
        "veredicto": auditoria.veredicto,
    }


def main() -> int:
    captured_at = dt.datetime.now(dt.timezone.utc).isoformat()
    fecha = captured_at[:10]

    df = run_snapshot(captured_at=captured_at)

    if df.empty:
        raise RuntimeError("La corrida de hoy no trajo ningún aviso — abortando antes de sobreescribir latest.json.")

    check_parse_rate(df.to_dict(orient="records"), field="price_usd", min_rate=0.9)

    rebuild_from_snapshots()  # valida que el schema completo sigue aplicando limpio

    current_snapshot_path = SNAPSHOTS_DIR / f"{fecha}.parquet"
    new_delistings = detect_delistings(df, SNAPSHOTS_DIR, current_snapshot_path, event_at=fecha)
    all_events = append_events(new_delistings, PRICE_EVENTS_PATH)

    latest = build_latest_json(df)
    latest["mi_propiedad"] = _audit_mi_propiedad(df)
    latest["n_desaparecidos_hoy"] = int(len(new_delistings))
    latest["n_eventos_acumulados"] = int(len(all_events))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        f"OK: {latest['n_avisos']} avisos publicados de {latest['n_avisos_total']} obtenidos. "
        f"{len(new_delistings)} avisos desaparecieron desde el snapshot anterior."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
