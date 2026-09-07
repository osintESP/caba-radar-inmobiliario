import types

from ingest.snapshot import _scrape_browser_portal


def test_scrape_browser_portal_skips_failing_combo_but_keeps_others():
    """Un combo que falla (ej. ChallengePageError de Cloudflare) no debe
    tirar los datos ya juntados de los demás barrios — regresión de un bug
    real encontrado en producción, donde un fallo silencioso en un combo
    hacía perder el resto de una corrida de horas."""
    barrios_cfg = {
        "nucleo": [{"nombre": "A", "meli_slug": "a"}],
        "propia": [{"nombre": "B", "meli_slug": "b"}],
        "anillo": [],
        "tipologias": ["departamento"],
    }

    def fake_search(browser, barrio_nombre, barrio_slug, tipo, max_pages=None):
        if barrio_nombre == "A":
            raise RuntimeError("Cloudflare no soltó el contenido real")
        yield {"portal_id": f"X-{barrio_nombre}", "barrio": barrio_nombre}

    fake_module = types.SimpleNamespace(__name__="fake_portal", search_barrio_tipo=fake_search)

    records = _scrape_browser_portal(fake_module, browser=None, barrios_cfg=barrios_cfg)

    assert len(records) == 1
    assert records[0]["barrio"] == "B"


def test_scrape_browser_portal_partial_pagination_failure_keeps_earlier_pages():
    """Si el combo falla recién en la página 2, la página 1 ya emitida no
    se pierde (list.extend consume el generador de a uno)."""
    barrios_cfg = {
        "nucleo": [],
        "propia": [{"nombre": "B", "meli_slug": "b"}],
        "anillo": [],
        "tipologias": ["departamento"],
    }

    def fake_search(browser, barrio_nombre, barrio_slug, tipo, max_pages=None):
        yield {"portal_id": "pagina-1"}
        raise RuntimeError("la pagina 2 no cargo")

    fake_module = types.SimpleNamespace(__name__="fake_portal", search_barrio_tipo=fake_search)

    records = _scrape_browser_portal(fake_module, browser=None, barrios_cfg=barrios_cfg)

    assert records == [{"portal_id": "pagina-1"}]
