from ingest import meli_scraper as ms


def test_slugify_strips_accents_and_spaces():
    assert ms.slugify("Vélez Sarsfield") == "velez-sarsfield"
    assert ms.slugify("Villa del Parque") == "villa-del-parque"


SEARCH_PAGE_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@graph":[
  {"@type":"RealEstateListing","name":"Depto test","offers":{"@type":"Offer","price":130000,"priceCurrency":"USD","url":"https://departamento.mercadolibre.com.ar/MLA-1111111111-depto-test-_JM"},"seller":{"@type":"Organization","name":"INMOBILIARIA X"},"datePosted":"2026-01-01"},
  {"@type":"RealEstateListing","name":"Depto test 2","offers":{"@type":"Offer","price":95000,"priceCurrency":"USD","url":"https://departamento.mercadolibre.com.ar/MLA-2222222222-depto-test-2-_JM"},"seller":{"@type":"Organization","name":"INMOBILIARIA Y"},"datePosted":"2026-02-01"}
]}
</script>
<script>window.__X__={"total":2}</script>
</body></html>
"""


def test_parse_search_results_extracts_listings():
    results = ms.parse_search_results(SEARCH_PAGE_HTML, tipo="departamento", barrio_hint="Monte Castro")
    assert len(results) == 2
    first = results[0]
    assert first["portal_id"] == "MLA1111111111"
    assert first["price_amount"] == 130000
    assert first["price_currency"] == "USD"
    assert first["seller"] == "INMOBILIARIA X"
    assert first["barrio"] == "Monte Castro"
    assert first["tipo"] == "departamento"
    assert first["status"] == "active"


def test_total_results_parses_total_field():
    assert ms.total_results(SEARCH_PAGE_HTML) == 2


def test_parse_search_results_ignores_malformed_ld_json():
    html = '<script type="application/ld+json">{not valid json</script>'
    assert ms.parse_search_results(html, "departamento", "Monte Castro") == []


DETAIL_PAGE_HTML = """
<html><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","itemCondition":"https:\\u002F\\u002Fschema.org\\u002FUsedCondition","sku":"MLA1111111111"}</script>
<table>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Superficie total</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">81,93 m²</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Superficie cubierta</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">75 m²</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Ambientes</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">4</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Baños</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">1</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Cocheras</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">1</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Antigüedad</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">15 años</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Expensas</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">140.000 ARS</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Ascensor</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">Sí</span></span></td></tr>
<tr class="andes-table__row"><th class="andes-table__header" scope="row"><div class="andes-table__header__container">Lavandería</div></th><td class="andes-table__column"><span><span class="andes-table__column--value">No</span></span></td></tr>
</table>
</body></html>
"""


def test_fetch_detail_parses_spec_table(monkeypatch):
    import httpx

    def fake_get(client, url):
        return httpx.Response(200, text=DETAIL_PAGE_HTML, request=httpx.Request("GET", url))

    monkeypatch.setattr(ms, "_get", fake_get)
    client = ms.make_client()
    result = ms.fetch_detail(client, "https://departamento.mercadolibre.com.ar/MLA-1111111111-x-_JM")

    assert result["m2_total"] == 81.93
    assert result["m2_cubiertos"] == 75.0
    assert result["ambientes"] == 4
    assert result["banos"] == 1
    assert result["cocheras"] == 1
    assert result["antiguedad"] == 15
    assert result["expensas_ars"] == 140000.0
    assert result["ascensor"] is True
    assert result["condicion"] == "usado"
    # Un label que no está en _SPEC_FIELD_MAP (Lavandería) se ignora, no rompe nada.
    assert result["dormitorios"] is None  # no vino en esta fixture -> None, nunca imputado


def test_fetch_detail_unknown_condition_stays_none(monkeypatch):
    import httpx

    html = "<html><body>sin tabla ni ld+json</body></html>"

    def fake_get(client, url):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(ms, "_get", fake_get)
    client = ms.make_client()
    result = ms.fetch_detail(client, "https://x")
    assert result["condicion"] is None
    assert result["m2_cubiertos"] is None


def test_parse_antiguedad_keeps_plausible_age_in_years():
    assert ms._parse_antiguedad("15 años") == 15
    assert ms._parse_antiguedad("0 (a estrenar)") == 0


def test_parse_antiguedad_converts_construction_year_to_age():
    import datetime as dt

    anio_actual = dt.date.today().year
    assert ms._parse_antiguedad("1970") == anio_actual - 1970
    assert ms._parse_antiguedad("1976 años") == anio_actual - 1976


def test_parse_antiguedad_missing_value_stays_none():
    assert ms._parse_antiguedad("sin dato") is None


def test_parse_cocheras_keeps_plausible_count():
    assert ms._parse_cocheras("2") == 2
    assert ms._parse_cocheras("0") == 0
    assert ms._parse_cocheras("4") == 4


def test_parse_cocheras_discards_implausible_aggregate_value():
    # Atributo de "Emprendimiento" (proyecto completo, no la unidad) — se
    # descarta a None en vez de propagar un número que sabemos mal.
    assert ms._parse_cocheras("10") is None


def test_parse_cocheras_missing_value_stays_none():
    assert ms._parse_cocheras("sin dato") is None
