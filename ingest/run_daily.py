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
5. Audita contra comparables reales (F4, sección 10) tanto "mi propiedad"
   como CADA candidata visible en la tabla, con exactamente el mismo motor
   (analysis/valuation.py::audit_property) — sin rama especial para ninguna.
6. Detecta avisos que desaparecieron o cambiaron de precio desde el
   snapshot anterior (F6, ingest/price_events.py) y los acumula en
   data/price_events.parquet.
7. Calcula la brecha neta (F5, analysis/brecha_neta.py) de cada aviso
   contra "mi propiedad", usando config/costos.yaml.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

from analysis.brecha_neta import brecha_neta
from analysis.db import rebuild_from_snapshots
from analysis.history import build_market_trends, build_price_history
from analysis.latest import build_latest_json, deduplicated_view
from analysis.valuation import audit_candidates, audit_property
from ingest.normalize import check_parse_rate
from ingest.price_events import append_events, detect_delistings, detect_price_changes
from ingest.snapshot import CONFIG_DIR, SNAPSHOTS_DIR, load_yaml, run_snapshot

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LATEST_JSON_PATH = DATA_DIR / "latest.json"
PRICE_EVENTS_PATH = DATA_DIR / "price_events.parquet"
PRICE_HISTORY_JSON_PATH = DATA_DIR / "price_history.json"
MARKET_TRENDS_JSON_PATH = DATA_DIR / "market_trends.json"


def _audit_mi_propiedad(comparables_pool, adyacentes: dict, mi_propiedad: dict) -> dict:
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
    new_price_changes = detect_price_changes(df, SNAPSHOTS_DIR, current_snapshot_path, event_at=fecha)
    all_events = append_events(pd.concat([new_delistings, new_price_changes], ignore_index=True), PRICE_EVENTS_PATH)

    adyacentes = load_yaml(CONFIG_DIR / "barrios.yaml").get("adyacentes", {})
    comparables_pool = deduplicated_view(df[(~df["es_outlier"].fillna(False)) & df["price_usd"].notna()])

    # F4 extendido a todo candidato visible, no solo "mi propiedad" (regla
    # anti-sesgo, analysis/valuation.py): mergea el percentil/mediana de
    # cada aviso contra el resto del pool antes de armar el JSON del sitio.
    candidatos_auditados = audit_candidates(comparables_pool, adyacentes)
    df = df.merge(candidatos_auditados, on="portal_id", how="left")

    # F5: cuánto hay que poner de más para pasarse de "mi propiedad" a cada
    # candidata (analysis/brecha_neta.py) — la columna que el plan dice que
    # debería ordenar toda la app, no el USD/m² de lista.
    costos = load_yaml(CONFIG_DIR / "costos.yaml")["costos"]
    mi_propiedad_cfg = load_yaml(CONFIG_DIR / "mi_propiedad.yaml")["mi_propiedad"]
    precio_venta_mio = mi_propiedad_cfg["precio_venta_max_usd"]
    df["brecha_neta_usd"] = df["price_usd"].map(
        lambda precio_lista: brecha_neta(precio_lista, precio_venta_mio, costos) if pd.notna(precio_lista) else None
    )

    latest = build_latest_json(df)
    latest["mi_propiedad"] = _audit_mi_propiedad(comparables_pool, adyacentes, mi_propiedad_cfg)
    latest["n_desaparecidos_hoy"] = int(len(new_delistings))
    latest["n_eventos_acumulados"] = int(len(all_events))
    if all_events.empty:
        latest["n_recortes_mes"] = 0
    else:
        hace_30_dias = pd.to_datetime(fecha) - pd.Timedelta(days=30)
        recortes_mes = (
            (all_events["event_type"] == "price_change")
            & (all_events["pct_change"] < 0)
            & (pd.to_datetime(all_events["event_at"]) >= hace_30_dias)
        )
        latest["n_recortes_mes"] = int(recortes_mes.sum())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LATEST_JSON_PATH.write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")

    # F6 (ficha de propiedad) y Vista de Mercado: series históricas a
    # través de todos los snapshots acumulados, no solo el de hoy.
    price_history = build_price_history(SNAPSHOTS_DIR)
    PRICE_HISTORY_JSON_PATH.write_text(json.dumps(price_history, ensure_ascii=False), encoding="utf-8")
    market_trends = build_market_trends(SNAPSHOTS_DIR)
    MARKET_TRENDS_JSON_PATH.write_text(json.dumps(market_trends, ensure_ascii=False), encoding="utf-8")

    print(
        f"OK: {latest['n_avisos']} avisos publicados de {latest['n_avisos_total']} obtenidos. "
        f"{len(new_delistings)} avisos desaparecieron y {len(new_price_changes)} cambiaron de precio "
        f"desde el snapshot anterior."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
