"""Reglas de normalización (PLAN-radar-inmobiliario.md, sección 8).

Recibe registros ya extraídos de un aviso crudo (ver ingest/meli_client.py,
que separa "parsear el payload del portal" de "aplicar las reglas de negocio"
que viven acá) y les aplica:

1. Moneda: todo a USD al dólar MEP del día, guardando la cotización usada.
2. Superficie: m2_cubiertos es la variable de valuación. Si falta, NULL y
   fuera del modelo — nunca imputar.
3. Precio a consultar: NULL, excluido del modelo, conservado para tracking.
4. Expensas: quedan en ARS, no se convierten. Entran al modelo.
5. Pozo vs usado: categorías separadas.
6. Outliers: se flaggean (no se descartan) fuera de 400-8000 USD/m2.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from ingest.fx_mep import MepRate

# Campos esperados en un ExtractedListing (dict), producidos por meli_client.py:
#   portal, portal_id, url, price_amount, price_currency, expensas_ars,
#   m2_total, m2_cubiertos, ambientes, dormitorios, banos, cocheras,
#   antiguedad, piso, ascensor, tipo, condicion, barrio, lat, lon,
#   titulo, descripcion, raw_json

ExtractedListing = dict[str, Any]
NormalizedRow = dict[str, Any]


def _to_usd(price_amount: Optional[float], price_currency: Optional[str], mep: MepRate) -> Optional[float]:
    if price_amount is None:
        return None
    if price_currency == "USD":
        return float(price_amount)
    if price_currency == "ARS":
        return float(price_amount) / mep.rate
    # Moneda desconocida/faltante: no se puede convertir con confianza.
    return None


def normalize_listing(
    record: ExtractedListing,
    mep: MepRate,
    usd_m2_min: float,
    usd_m2_max: float,
    captured_at: Optional[str] = None,
) -> NormalizedRow:
    captured_at = captured_at or dt.datetime.now(dt.timezone.utc).isoformat()

    price_usd = _to_usd(record.get("price_amount"), record.get("price_currency"), mep)

    m2_cubiertos = record.get("m2_cubiertos")  # None se mantiene None, nunca se imputa

    usd_m2 = None
    if price_usd is not None and m2_cubiertos:
        usd_m2 = price_usd / m2_cubiertos

    es_outlier = False
    outlier_reason = None
    if usd_m2 is not None and not (usd_m2_min <= usd_m2 <= usd_m2_max):
        es_outlier = True
        outlier_reason = f"usd_m2={usd_m2:.0f} fuera de [{usd_m2_min:.0f}, {usd_m2_max:.0f}]"

    return {
        "portal": record.get("portal"),
        "portal_id": record.get("portal_id"),
        "url": record.get("url"),
        "status": record.get("status") or "active",
        "captured_at": captured_at,
        "price_amount": record.get("price_amount"),
        "price_currency": record.get("price_currency"),
        "price_usd": price_usd,
        "usd_m2": usd_m2,
        "fx_rate_used": mep.rate,
        "fx_source": mep.source,
        "fx_fetched_at": mep.fetched_at,
        "expensas_ars": record.get("expensas_ars"),
        "m2_total": record.get("m2_total"),
        "m2_cubiertos": m2_cubiertos,
        "ambientes": record.get("ambientes"),
        "dormitorios": record.get("dormitorios"),
        "banos": record.get("banos"),
        "cocheras": record.get("cocheras"),
        "antiguedad": record.get("antiguedad"),
        "piso": record.get("piso"),
        "ascensor": record.get("ascensor"),
        "tipo": record.get("tipo"),
        "condicion": record.get("condicion"),  # 'pozo'|'usado'
        "barrio": record.get("barrio"),
        "lat": record.get("lat"),
        "lon": record.get("lon"),
        "titulo": record.get("titulo"),
        "descripcion": record.get("descripcion"),
        "tags": record.get("tags"),
        "direccion": record.get("direccion"),
        "imagen_url": record.get("imagen_url"),
        "es_outlier": es_outlier,
        "outlier_reason": outlier_reason,
        "raw_json": record.get("raw_json"),
    }


def normalize_batch(
    records: list[ExtractedListing],
    mep: MepRate,
    usd_m2_min: float,
    usd_m2_max: float,
    captured_at: Optional[str] = None,
) -> list[NormalizedRow]:
    return [normalize_listing(r, mep, usd_m2_min, usd_m2_max, captured_at) for r in records]


def check_parse_rate(rows: list[NormalizedRow], field: str = "price_usd", min_rate: float = 0.9) -> float:
    """Tasa de filas con `field` no nulo. Riesgo #1 del proyecto (sección 13
    del doc): un cambio de formato del portal que rompe el parser en
    silencio es peor que el job caído. El caller debe fallar ruidosamente
    (excepción, no un log) si esto cae por debajo del umbral.
    """
    if not rows:
        raise ValueError("check_parse_rate: no hay filas para evaluar (0 avisos obtenidos).")
    n_ok = sum(1 for r in rows if r.get(field) is not None)
    rate = n_ok / len(rows)
    if rate < min_rate:
        raise ValueError(
            f"Tasa de parseo de '{field}' cayó a {rate:.1%} (< {min_rate:.0%} requerido, "
            f"{n_ok}/{len(rows)} filas OK). Posible cambio de formato del portal."
        )
    return rate
