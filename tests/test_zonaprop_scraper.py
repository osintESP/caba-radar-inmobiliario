from ingest import zonaprop_scraper as zp

SEARCH_PAGE_HTML = """
<html><body>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"RealEstateListing","offers":{"@type":"AggregateOffer","highPrice":239000,"lowPrice":43000,"offerCount":"385"}}</script>
<div class="postingCard-module__posting-container"><div class="postingCard-module__posting-top"><h2 class="postingPrices-module__price" data-qa="POSTING_CARD_PRICE">USD 67.000</h2><h2 class="postingPrices-module__expenses" data-qa="expensas">$ 110.000 Expensas</h2><h3 data-qa="POSTING_CARD_FEATURES"><span class="postingMainFeatures-module__posting-main-features-span">29 m² tot.</span><span class="postingMainFeatures-module__posting-main-features-span">1 amb.</span><span class="postingMainFeatures-module__posting-main-features-span">1 baño</span></h3><h4 class="postingLocations-module__location-address-in-listing">Benito Juárez al 2100</h4><h4 class="postingLocations-module__location-text" data-qa="POSTING_CARD_LOCATION">Monte Castro, Capital Federal</h4><a href="/propiedades/clasificado/depto-monte-castro-59761247.html?n_src=Listado">ver</a></div></div>
<div class="postingCard-module__posting-container"><div class="postingCard-module__posting-top"><h2 class="postingPrices-module__price" data-qa="POSTING_CARD_PRICE">USD 107.800</h2><h3 data-qa="POSTING_CARD_FEATURES"><span class="postingMainFeatures-module__posting-main-features-span">49 m² tot.</span><span class="postingMainFeatures-module__posting-main-features-span">2 amb.</span><span class="postingMainFeatures-module__posting-main-features-span">1 baño</span><span class="postingMainFeatures-module__posting-main-features-span">1 coch.</span></h3><h4 class="postingLocations-module__location-address-in-listing">Bahia Blanca al 2400</h4><h4 class="postingLocations-module__location-text" data-qa="POSTING_CARD_LOCATION">Monte Castro, Capital Federal</h4><a href="/propiedades/clasificado/depto-2amb-monte-castro-57115623.html?n_src=Listado">ver</a></div></div>
</body></html>
"""


def test_parse_search_results_extracts_cards():
    results = zp.parse_search_results(SEARCH_PAGE_HTML, tipo="departamento", barrio_hint="Monte Castro")
    assert len(results) == 2

    first = results[0]
    assert first["portal"] == "zonaprop"
    assert first["portal_id"] == "ZP59761247"
    assert first["price_amount"] == 67000.0
    assert first["price_currency"] == "USD"
    assert first["expensas_ars"] == 110000.0
    assert first["m2_total"] == 29.0
    assert first["ambientes"] == 1
    assert first["banos"] == 1
    assert first["direccion"] == "Benito Juárez al 2100"
    assert first["barrio"] == "Monte Castro"
    assert first["tipo"] == "departamento"
    assert first["url"].endswith("59761247.html")

    second = results[1]
    assert second["cocheras"] == 1


def test_total_results_parses_offer_count():
    assert zp.total_results(SEARCH_PAGE_HTML) == 385


def test_build_search_url_pagination():
    assert zp.build_search_url("departamento", "monte-castro", page=1) == (
        "https://www.zonaprop.com.ar/departamentos-venta-monte-castro.html"
    )
    assert zp.build_search_url("departamento", "monte-castro", page=2) == (
        "https://www.zonaprop.com.ar/departamentos-venta-monte-castro-pagina-2.html"
    )


def test_no_cards_returns_empty_list():
    assert zp.parse_search_results("<html><body>sin avisos</body></html>", "departamento", "Monte Castro") == []
