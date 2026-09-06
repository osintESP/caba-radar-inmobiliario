import pytest

from ingest.fx_mep import MepRate


@pytest.fixture
def mep() -> MepRate:
    return MepRate(rate=1000.0, source="dolarapi:bolsa", fetched_at="2026-09-06T12:00:00+00:00")


@pytest.fixture
def extracted_factory():
    return make_extracted


def make_extracted(**overrides):
    base = {
        "portal": "meli",
        "portal_id": "MLA1",
        "url": "https://articulo.mercadolibre.com.ar/MLA1",
        "status": "active",
        "price_amount": 150_000_000.0,
        "price_currency": "ARS",
        "expensas_ars": 45_000.0,
        "m2_total": 75.0,
        "m2_cubiertos": 72.0,
        "ambientes": 3,
        "dormitorios": 2,
        "banos": 1,
        "cocheras": 0,
        "antiguedad": 30,
        "piso": 4,
        "ascensor": True,
        "tipo": "departamento",
        "condicion": "usado",
        "barrio": "Monte Castro",
        "lat": -34.62,
        "lon": -58.51,
        "titulo": "Depto 3 amb Monte Castro",
        "descripcion": None,
        "raw_json": "{}",
    }
    base.update(overrides)
    return base
