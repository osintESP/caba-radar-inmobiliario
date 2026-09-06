"""Cotización del dólar MEP ("bolsa"), nunca el oficial.

Fuente primaria: dolarapi.com (gratuita, sin auth, separa bolsa/oficial/blue).
Fallback: criptoya.com. Si ambas fallan, se propaga la excepción — no tiene
sentido normalizar precios con una cotización vieja sin decirlo.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import httpx

DOLARAPI_URL = "https://dolarapi.com/v1/dolares/bolsa"
CRIPTOYA_URL = "https://criptoya.com/api/dolar"

_TIMEOUT = 10.0


@dataclass(frozen=True)
class MepRate:
    rate: float
    source: str
    fetched_at: str  # ISO 8601 UTC


def _fetch_dolarapi(client: httpx.Client, price_field: str) -> MepRate:
    resp = client.get(DOLARAPI_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return MepRate(
        rate=float(data[price_field]),
        source="dolarapi:bolsa",
        fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


def _fetch_criptoya(client: httpx.Client, price_field: str) -> MepRate:
    resp = client.get(CRIPTOYA_URL, timeout=_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    mep = data["mep"]
    # criptoya usa "ask"/"bid"; "venta" del doc equivale a "ask" (lo que hay que
    # pagar para comprar dólares, i.e. ARS necesarios por 1 USD).
    field_map = {"venta": "ask", "compra": "bid"}
    return MepRate(
        rate=float(mep[field_map.get(price_field, price_field)]),
        source="criptoya:mep",
        fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


def get_mep_rate(price_field: str = "venta", client: httpx.Client | None = None) -> MepRate:
    """Devuelve la cotización MEP del momento, con fallback.

    `price_field` viene de config/costos.yaml (`fx.mep_price_field`), nunca
    hardcodeado en el código.
    """
    owns_client = client is None
    client = client or httpx.Client()
    try:
        try:
            return _fetch_dolarapi(client, price_field)
        except (httpx.HTTPError, KeyError, ValueError):
            return _fetch_criptoya(client, price_field)
    finally:
        if owns_client:
            client.close()
