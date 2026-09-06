import httpx
import pytest
import respx

from ingest.fx_mep import CRIPTOYA_URL, DOLARAPI_URL, get_mep_rate


@respx.mock
def test_dolarapi_bolsa_used_by_default():
    respx.get(DOLARAPI_URL).mock(
        return_value=httpx.Response(200, json={"compra": 1490.0, "venta": 1510.0, "fechaActualizacion": "2026-09-06T12:00:00Z"})
    )
    rate = get_mep_rate(price_field="venta")
    assert rate.rate == 1510.0
    assert rate.source == "dolarapi:bolsa"


@respx.mock
def test_fx_never_uses_oficial_house():
    """Guarda de regresión: si alguien cambia por error DOLARAPI_URL a la casa
    'oficial', este test debe fallar — nunca se debe pedir el dólar oficial."""
    assert "/bolsa" in DOLARAPI_URL
    assert "oficial" not in DOLARAPI_URL


@respx.mock
def test_falls_back_to_criptoya_when_dolarapi_down():
    respx.get(DOLARAPI_URL).mock(return_value=httpx.Response(503))
    respx.get(CRIPTOYA_URL).mock(
        return_value=httpx.Response(200, json={"mep": {"bid": 1495.0, "ask": 1512.0}})
    )
    rate = get_mep_rate(price_field="venta")
    assert rate.rate == 1512.0
    assert rate.source == "criptoya:mep"


@respx.mock
def test_raises_when_both_sources_fail():
    respx.get(DOLARAPI_URL).mock(return_value=httpx.Response(503))
    respx.get(CRIPTOYA_URL).mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        get_mep_rate(price_field="venta")
