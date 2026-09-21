from ingest.perimetro import apply_perimetros, fuera_de_perimetro, point_in_polygon

CUADRADO = [[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0]]


def test_point_in_polygon():
    assert point_in_polygon(5, 5, CUADRADO)
    assert not point_in_polygon(15, 5, CUADRADO)
    assert not point_in_polygon(5, -1, CUADRADO)


def test_sin_poligono_no_filtra():
    assert not fuera_de_perimetro("Floresta", 99.0, 99.0, {})
    assert not fuera_de_perimetro("Floresta", 99.0, 99.0, {"Floresta": []})


def test_sin_coordenadas_no_se_oculta():
    assert not fuera_de_perimetro("Floresta", None, None, {"Floresta": CUADRADO})


def test_barrio_sin_perimetro_no_se_toca():
    assert not fuera_de_perimetro("Monte Castro", 99.0, 99.0, {"Floresta": CUADRADO})


def test_apply_perimetros_marca_filas():
    rows = [
        {"barrio": "Floresta", "lat": 5.0, "lon": 5.0},
        {"barrio": "Floresta", "lat": 50.0, "lon": 5.0},
        {"barrio": "Floresta", "lat": float("nan"), "lon": float("nan")},
    ]
    apply_perimetros(rows, {"Floresta": CUADRADO})
    assert [r["fuera_de_perimetro"] for r in rows] == [False, True, False]
