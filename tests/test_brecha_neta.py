from analysis.brecha_neta import brecha_neta, costo_compra, neto_venta

COSTOS = {
    "comision_venta_pct": 0.03,
    "comision_compra_pct": 0.03,
    "iva_sobre_comision": 0.21,
    "sellos_pct": 0.027,
    "sellos_a_mi_cargo_pct": 0.5,
    "escritura_pct": 0.02,
    "gastos_fijos_usd": 1500,
    "impuesto_transferencia_pct": 0.0,
    "brecha_negociacion_pct": 0.06,
}


def test_neto_venta_resta_comision_con_iva_y_gastos_fijos():
    resultado = neto_venta(130000, COSTOS)
    comision_con_iva = 130000 * 0.03 * 1.21
    assert resultado == 130000 - comision_con_iva - 1500


def test_neto_venta_resta_impuesto_transferencia_si_aplica():
    costos = {**COSTOS, "impuesto_transferencia_pct": 0.015}
    resultado = neto_venta(130000, costos)
    comision_con_iva = 130000 * 0.03 * 1.21
    impuesto = 130000 * 0.015
    assert resultado == 130000 - comision_con_iva - impuesto - 1500


def test_costo_compra_aplica_la_brecha_de_negociacion_antes_de_los_costos():
    resultado = costo_compra(150000, COSTOS)
    negociado = 150000 * 0.94
    sellos = negociado * 0.027 * 0.5
    escritura = negociado * 0.02
    comision_con_iva = negociado * 0.03 * 1.21
    assert resultado == negociado + sellos + escritura + comision_con_iva + 1500


def test_brecha_neta_positiva_cuando_la_candidata_es_mas_cara():
    # Candidata bastante más cara que "mi propiedad": hay que poner de más.
    resultado = brecha_neta(precio_lista_usd=250000, precio_venta_usd=130000, costos=COSTOS)
    assert resultado > 0
    assert resultado == costo_compra(250000, COSTOS) - neto_venta(130000, COSTOS)


def test_brecha_neta_negativa_cuando_la_candidata_es_mas_barata():
    # Candidata bastante más barata: sobra plata al pasarse.
    resultado = brecha_neta(precio_lista_usd=60000, precio_venta_usd=130000, costos=COSTOS)
    assert resultado < 0
