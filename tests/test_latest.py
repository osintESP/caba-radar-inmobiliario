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
        "banos": 1,
        "cocheras": 0,
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
        "es_nuevo": False,
        "tags": None,
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


def test_duplicate_group_shows_only_cheapest_with_count():
    """F3: dos avisos con el mismo property_fingerprint (mismo grupo de
    dedupe) se muestran como uno solo, el de menor precio, con
    n_duplicados=2 — el resto sigue existiendo en el DataFrame, solo no
    se repite en la vista."""
    df = pd.DataFrame(
        [
            _row(portal_id="MLA1", price_usd=135000.0, property_fingerprint="grp_MLA1"),
            _row(portal_id="ZP1", price_usd=130000.0, property_fingerprint="grp_MLA1"),
            _row(portal_id="AP9", price_usd=99000.0, property_fingerprint="AP9"),  # sin duplicados
        ]
    )
    latest = build_latest_json(df)
    assert latest["n_avisos"] == 2  # el grupo de 2 cuenta como 1 en la vista
    assert latest["n_avisos_total"] == 3  # pero las 3 filas siguen en el DataFrame

    avisos_por_precio = {a["price_usd"]: a for a in latest["avisos"]}
    assert 130000.0 in avisos_por_precio  # el más barato del grupo, no el de 135000
    assert 135000.0 not in avisos_por_precio
    assert avisos_por_precio[130000.0]["n_duplicados"] == 2
    assert avisos_por_precio[99000.0]["n_duplicados"] == 1
