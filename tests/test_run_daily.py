import pandas as pd

from ingest.run_daily import _audit_mi_propiedad


def test_audit_mi_propiedad_sin_m2_devuelve_sin_datos_no_rompe():
    """config/mi_propiedad_papa.yaml arranca con m2_cubiertos=null (dato
    real, no imputado) — _audit_mi_propiedad() no debe dividir por None,
    tiene que degradar a un resultado explícito de "faltan datos"."""
    mi_propiedad = {
        "barrio": "Merlo",
        "tipo": "casa",
        "ambientes": None,
        "m2_cubiertos": None,
        "precio_venta_max_usd": 100000,
    }
    resultado = _audit_mi_propiedad(pd.DataFrame(), adyacentes={}, mi_propiedad=mi_propiedad)
    assert resultado["veredicto"] == "sin_datos"
    assert resultado["usd_m2_declarado"] is None
    assert resultado["percentil_sujeto"] is None
    assert resultado["precio_venta_max_usd"] == 100000


def test_audit_mi_propiedad_con_m2_corre_la_auditoria_normal():
    comparables = pd.DataFrame(
        [
            {
                "portal_id": f"MLA{i}",
                "barrio": "Monte Castro",
                "tipo": "departamento",
                "condicion": "usado",
                "ambientes": 3,
                "m2_cubiertos": 70.0,
                "usd_m2": 1800.0 + i,
            }
            for i in range(30)
        ]
    )
    mi_propiedad = {
        "barrio": "Monte Castro",
        "tipo": "departamento",
        "ambientes": 3,
        "m2_cubiertos": 72.0,
        "precio_venta_max_usd": 130000,
    }
    resultado = _audit_mi_propiedad(comparables, adyacentes={}, mi_propiedad=mi_propiedad)
    assert resultado["veredicto"] == "ok"
    assert resultado["n_comparables"] == 30
    assert resultado["usd_m2_declarado"] == 130000 / 72.0
