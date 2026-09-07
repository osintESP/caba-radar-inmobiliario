import json

import pandas as pd

from analysis.latest import build_latest_json


def _row(**overrides):
    base = {
        "portal": "meli",
        "portal_id": "MLA1",
        "barrio": "Monte Castro",
        "tipo": "departamento",
        "condicion": "usado",
        "ambientes": 3,
        "m2_cubiertos": 72.0,
        "price_usd": 130000.0,
        "usd_m2": 1805.5,
        "expensas_ars": 50000.0,
        "antiguedad": 30,
        "piso": None,  # dato faltante real (no todos los avisos lo tienen)
        "ascensor": True,
        "url": "https://x/1",
        "captured_at": "2026-09-06T12:00:00Z",
        "fx_rate_used": 1500.0,
        "fx_source": "dolarapi:bolsa",
        "es_outlier": False,
    }
    base.update(overrides)
    return base


def test_missing_numeric_field_serializes_as_null_not_nan():
    """Regresión: pandas castea None a NaN en columnas float, y
    json.dumps(NaN) produce el literal `NaN`, JSON inválido que rompe
    JSON.parse() en el navegador (bug real encontrado en producción)."""
    df = pd.DataFrame([_row(piso=None)])
    latest = build_latest_json(df)
    dumped = json.dumps(latest)

    assert "NaN" not in dumped
    # roundtrip: json.loads con json estándar (allow_nan=False) no debe fallar
    reparsed = json.loads(dumped)
    assert reparsed["avisos"][0]["piso"] is None


def test_multiple_missing_fields_all_become_null():
    df = pd.DataFrame(
        [
            _row(portal_id="MLA1", piso=None, antiguedad=None),
            _row(portal_id="MLA2", ambientes=None, expensas_ars=None),
        ]
    )
    latest = build_latest_json(df)
    dumped = json.dumps(latest)
    assert "NaN" not in dumped
    json.loads(dumped)  # no debe tirar ValueError


def test_no_missing_fields_still_serializes_correctly():
    df = pd.DataFrame([_row()])
    latest = build_latest_json(df)
    dumped = json.dumps(latest)
    reparsed = json.loads(dumped)
    assert reparsed["avisos"][0]["ambientes"] == 3
