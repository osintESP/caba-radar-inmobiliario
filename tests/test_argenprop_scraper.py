from ingest import argenprop_scraper as ap

SEARCH_PAGE_HTML = """
<html><head><title>468 Departamentos en venta en Monte Castro, CABA - Argenprop</title></head><body>
<a href="/departamento-en-venta-en-monte-castro-1-ambiente--20227758" target="_blank" id="id-card-1" class="card " data-item-card="20227758" idaviso="20227758" ambientes="" dormitorios="1" idmoneda="2" montooperacion="67900">
  <div class="card__details-box">
    <p class="card__price"><span class="card__currency">USD</span> 67.900</p>
    <p class="card__address" data-card-direccion="">Miranda 5000</p>
    <h2 class="card__title">Hermoso monoambiente divisible apto credito</h2>
    <ul class="card__main-features">
      <li><i class="basico1-icon-superficie_cubierta"></i><span> 36  m² cubie. </span></li>
      <li><i class="basico1-icon-cantidad_dormitorios"></i><span> 1 dorm. </span></li>
      <li><i class="basico1-icon-antiguedad"></i><span> 10 años </span></li>
    </ul>
  </div>
</a>
<a href="/departamento-en-venta-en-monte-castro-2-ambientes--19464492" target="_blank" id="id-card-2" class="card " data-item-card="19464492" idaviso="19464492" ambientes="2" dormitorios="1" idmoneda="2" montooperacion="109000">
  <div class="card__details-box">
    <p class="card__price"><span class="card__currency">USD</span> 109.000</p>
    <p class="card__address" data-card-direccion="">Lascano 4000, Piso 7</p>
    <h2 class="card__title">2AMB todo luz y sol</h2>
    <ul class="card__main-features">
      <li><i class="basico1-icon-superficie_cubierta"></i><span> 45  m² cubie. </span></li>
      <li><i class="basico1-icon-cantidad_dormitorios"></i><span> 1 dorm. </span></li>
      <li><i class="basico1-icon-antiguedad"></i><span> A Estrenar </span></li>
    </ul>
  </div>
</a>
</body></html>
"""


def test_parse_search_results_extracts_cards():
    results = ap.parse_search_results(SEARCH_PAGE_HTML, tipo="departamento", barrio_hint="Monte Castro")
    assert len(results) == 2

    first = results[0]
    assert first["portal"] == "argenprop"
    assert first["portal_id"] == "AP20227758"
    assert first["price_amount"] == 67900.0
    assert first["price_currency"] == "USD"
    assert first["m2_cubiertos"] == 36.0
    assert first["dormitorios"] == 1
    assert first["antiguedad"] == 10
    assert first["condicion"] == "usado"
    assert first["direccion"] == "Miranda 5000"
    assert first["piso"] is None  # esta dirección no trae "Piso N"
    # ambientes="" en el tag: se completa con el número de la URL
    assert first["ambientes"] == 1

    second = results[1]
    assert second["ambientes"] == 2  # viene directo del atributo del tag
    assert second["piso"] == 7  # extraído de "Lascano 4000, Piso 7"
    assert second["antiguedad"] == 0
    assert second["condicion"] == "pozo"


def test_total_results_parses_title():
    assert ap.total_results(SEARCH_PAGE_HTML) == 468


def test_build_search_url_pagination():
    assert ap.build_search_url("departamento", "monte-castro", page=1) == (
        "https://www.argenprop.com/departamentos/venta/monte-castro"
    )
    assert ap.build_search_url("departamento", "monte-castro", page=2) == (
        "https://www.argenprop.com/departamentos/venta/monte-castro?pagina-2"
    )


def test_no_cards_returns_empty_list():
    assert ap.parse_search_results("<html><body>sin avisos</body></html>", "departamento", "Monte Castro") == []
