import types

import pandas as pd

from ingest.snapshot import (
    _enrich_descriptions,
    _scrape_browser_portal,
    all_barrios,
    apply_alcance_filter,
    load_known_descriptions,
    load_known_portal_ids,
)


def test_all_barrios_includes_anillo_by_default():
    barrios_cfg = {
        "nucleo": [{"nombre": "Velez Sarsfield", "meli_slug": "velez-sarsfield"}],
        "propia": [{"nombre": "Monte Castro", "meli_slug": "monte-castro"}],
        "anillo": [{"nombre": "Flores", "meli_slug": "flores"}],
    }
    assert all_barrios(barrios_cfg) == [
        ("Velez Sarsfield", "velez-sarsfield"),
        ("Monte Castro", "monte-castro"),
        ("Flores", "flores"),
    ]


def test_all_barrios_excludes_anillo_when_alcance_lo_desactiva():
    """Alcance reducido a pedido del usuario (config/barrios.yaml:
    alcance.anillo_activo: false) — solo núcleo + propia."""
    barrios_cfg = {
        "nucleo": [{"nombre": "Velez Sarsfield", "meli_slug": "velez-sarsfield"}],
        "propia": [{"nombre": "Monte Castro", "meli_slug": "monte-castro"}],
        "anillo": [{"nombre": "Flores", "meli_slug": "flores"}],
        "alcance": {"anillo_activo": False},
    }
    assert all_barrios(barrios_cfg) == [
        ("Velez Sarsfield", "velez-sarsfield"),
        ("Monte Castro", "monte-castro"),
    ]


def test_apply_alcance_filter_none_is_noop():
    rows = [{"ambientes": 1}, {"ambientes": None}]
    assert apply_alcance_filter(rows, None) == rows


def test_apply_alcance_filter_descarta_pocos_ambientes_y_sin_dato():
    rows = [
        {"portal_id": "A", "ambientes": 3},
        {"portal_id": "B", "ambientes": 2},
        {"portal_id": "C", "ambientes": None},
        {"portal_id": "D", "ambientes": 4},
    ]
    resultado = apply_alcance_filter(rows, ambientes_min=3)
    assert {r["portal_id"] for r in resultado} == {"A", "D"}


def test_load_known_portal_ids_reads_all_prior_snapshots(tmp_path):
    pd.DataFrame([{"portal_id": "A", "otro": 1}, {"portal_id": "B", "otro": 2}]).to_parquet(
        tmp_path / "2026-01-01.parquet", index=False
    )
    pd.DataFrame([{"portal_id": "B", "otro": 3}, {"portal_id": "C", "otro": 4}]).to_parquet(
        tmp_path / "2026-01-02.parquet", index=False
    )

    known = load_known_portal_ids(tmp_path)

    assert known == {"A", "B", "C"}


def test_load_known_portal_ids_empty_dir_returns_empty_set(tmp_path):
    assert load_known_portal_ids(tmp_path) == set()


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


def test_load_known_descriptions_skips_rows_without_descripcion(tmp_path):
    pd.DataFrame(
        [
            {"portal_id": "A", "descripcion": "apto credito y quincho", "tags": "apto_credito,quincho"},
            {"portal_id": "B", "descripcion": None, "tags": None},  # nunca se enriqueció
        ]
    ).to_parquet(tmp_path / "2026-01-01.parquet", index=False)

    known = load_known_descriptions(tmp_path)

    assert set(known) == {"A"}
    assert known["A"]["tags"] == "apto_credito,quincho"


def test_enrich_descriptions_skips_portals_without_fetch_description():
    records = [{"portal_id": "AP1", "url": "https://x"}]
    fake_module = types.SimpleNamespace(__name__="fake_portal")  # sin fetch_description

    _enrich_descriptions(records, fake_module, browser=None, snapshots_dir=None, barrios_cfg={})

    assert "descripcion" not in records[0]  # no se tocó nada


def test_enrich_descriptions_fetches_new_and_reuses_known(tmp_path):
    pd.DataFrame(
        [{"portal_id": "ZP1", "descripcion": "ya conocido apto credito", "tags": "apto_credito"}]
    ).to_parquet(tmp_path / "2026-01-01.parquet", index=False)

    calls = []

    def fake_fetch_description(browser, url):
        calls.append(url)
        return "PH con quincho y parrilla"

    fake_module = types.SimpleNamespace(__name__="fake_portal", fetch_description=fake_fetch_description)

    records = [
        {"portal_id": "ZP1", "url": "https://x/1"},  # ya conocido, no debe pedir de nuevo
        {"portal_id": "ZP2", "url": "https://x/2"},  # nuevo, se pide
    ]
    barrios_cfg = {"scraping": {"max_new_descriptions_por_corrida": 10}}

    _enrich_descriptions(records, fake_module, browser=None, snapshots_dir=tmp_path, barrios_cfg=barrios_cfg)

    assert calls == ["https://x/2"]  # solo se pidio la del nuevo
    assert records[0]["descripcion"] == "ya conocido apto credito"
    assert records[0]["tags"] == "apto_credito"
    assert records[1]["descripcion"] == "PH con quincho y parrilla"
    assert set(records[1]["tags"].split(",")) == {"quincho", "parrilla"}


def test_enrich_descriptions_respects_daily_cap(tmp_path):
    def fake_fetch_description(browser, url):
        return "algo apto credito"

    fake_module = types.SimpleNamespace(__name__="fake_portal", fetch_description=fake_fetch_description)
    records = [{"portal_id": f"ZP{i}", "url": f"https://x/{i}"} for i in range(5)]
    barrios_cfg = {"scraping": {"max_new_descriptions_por_corrida": 2}}

    _enrich_descriptions(records, fake_module, browser=None, snapshots_dir=tmp_path, barrios_cfg=barrios_cfg)

    con_descripcion = [r for r in records if r.get("descripcion") is not None]
    assert len(con_descripcion) == 2  # respeta el tope, el resto queda para mañana
