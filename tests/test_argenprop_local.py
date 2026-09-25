from ingest import argenprop_local
from ingest.browser_utils import ChallengePageError

CFG = {
    "nucleo": [{"nombre": "Floresta", "meli_slug": "floresta"}],
    "propia": [{"nombre": "Monte Castro", "meli_slug": "monte-castro"}],
    "alcance": {"anillo_activo": False},
    "tipologias": ["departamento", "ph"],
}


def test_frena_ante_captcha_y_descarta_la_combinacion_a_medias(monkeypatch):
    llamadas = []

    def fake_search(browser, nombre, slug, tipo, max_pages=None):
        llamadas.append((nombre, tipo))
        yield {"portal_id": f"AP-{nombre}-{tipo}-1", "barrio": nombre, "tipo": tipo}
        if (nombre, tipo) == ("Floresta", "ph"):
            raise ChallengePageError("captcha")  # a mitad de paginación

    monkeypatch.setattr(argenprop_local.argenprop_scraper, "search_barrio_tipo", fake_search)
    records, pendientes = argenprop_local.scrape_combos(None, CFG, max_pages=None)

    assert [r["portal_id"] for r in records] == ["AP-Floresta-departamento-1"]
    assert pendientes == 3  # Floresta/ph (a medias) + las 2 de Monte Castro
    assert llamadas == [("Floresta", "departamento"), ("Floresta", "ph")]  # no siguió pidiendo


def test_error_de_red_en_un_combo_no_frena_los_demas(monkeypatch):
    def fake_search(browser, nombre, slug, tipo, max_pages=None):
        if tipo == "ph":
            raise TimeoutError("red")
        yield {"portal_id": f"AP-{nombre}", "barrio": nombre, "tipo": tipo}

    monkeypatch.setattr(argenprop_local.argenprop_scraper, "search_barrio_tipo", fake_search)
    records, pendientes = argenprop_local.scrape_combos(None, CFG, max_pages=None)
    assert [r["portal_id"] for r in records] == ["AP-Floresta", "AP-Monte Castro"]
    assert pendientes == 0
