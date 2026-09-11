import pandas as pd

from analysis.history import build_market_trends, build_price_history


def _snapshot(rows):
    return pd.DataFrame(rows)


def _row(portal_id, barrio="Monte Castro", price_usd=130000.0, usd_m2=1800.0, es_outlier=False, portal="meli"):
    return {
        "portal": portal,
        "portal_id": portal_id,
        "barrio": barrio,
        "usd_m2": usd_m2,
        "price_usd": price_usd,
        "es_outlier": es_outlier,
    }


def test_build_price_history_empty_dir_returns_empty_dict(tmp_path):
    assert build_price_history(tmp_path) == {}


def test_build_price_history_tracks_series_per_listing_sorted_by_date(tmp_path):
    _snapshot([_row("A", price_usd=130000.0)]).to_parquet(tmp_path / "2026-01-01.parquet", index=False)
    _snapshot([_row("A", price_usd=125000.0)]).to_parquet(tmp_path / "2026-01-02.parquet", index=False)

    historial = build_price_history(tmp_path)

    assert list(historial.keys()) == ["meli:A"]
    assert historial["meli:A"] == [
        {"fecha": "2026-01-01", "price_usd": 130000.0},
        {"fecha": "2026-01-02", "price_usd": 125000.0},
    ]


def test_build_price_history_excludes_days_without_price(tmp_path):
    _snapshot([_row("A", price_usd=None)]).to_parquet(tmp_path / "2026-01-01.parquet", index=False)

    historial = build_price_history(tmp_path)
    assert historial == {}


def test_build_price_history_separates_same_portal_id_across_portals(tmp_path):
    _snapshot([_row("1", portal="meli"), _row("1", portal="zonaprop")]).to_parquet(
        tmp_path / "2026-01-01.parquet", index=False
    )

    historial = build_price_history(tmp_path)
    assert set(historial.keys()) == {"meli:1", "zonaprop:1"}


def test_build_market_trends_empty_dir_returns_empty_dict(tmp_path):
    assert build_market_trends(tmp_path) == {}


def test_build_market_trends_computes_median_and_count_per_barrio(tmp_path):
    _snapshot(
        [
            _row("A", barrio="Monte Castro", usd_m2=1800.0),
            _row("B", barrio="Monte Castro", usd_m2=2200.0),
            _row("C", barrio="Floresta", usd_m2=1500.0),
        ]
    ).to_parquet(tmp_path / "2026-01-01.parquet", index=False)

    tendencias = build_market_trends(tmp_path)

    assert tendencias["Monte Castro"] == [{"fecha": "2026-01-01", "mediana_usd_m2": 2000.0, "n_avisos": 2}]
    assert tendencias["Floresta"] == [{"fecha": "2026-01-01", "mediana_usd_m2": 1500.0, "n_avisos": 1}]


def test_build_market_trends_excludes_outliers_and_missing_usd_m2(tmp_path):
    _snapshot(
        [
            _row("A", barrio="Monte Castro", usd_m2=1800.0),
            _row("B", barrio="Monte Castro", usd_m2=9000.0, es_outlier=True),
            _row("C", barrio="Monte Castro", usd_m2=None),
        ]
    ).to_parquet(tmp_path / "2026-01-01.parquet", index=False)

    tendencias = build_market_trends(tmp_path)
    assert tendencias["Monte Castro"] == [{"fecha": "2026-01-01", "mediana_usd_m2": 1800.0, "n_avisos": 1}]


def test_build_market_trends_orders_series_by_date(tmp_path):
    _snapshot([_row("A", barrio="Monte Castro", usd_m2=1800.0)]).to_parquet(
        tmp_path / "2026-01-02.parquet", index=False
    )
    _snapshot([_row("B", barrio="Monte Castro", usd_m2=1700.0)]).to_parquet(
        tmp_path / "2026-01-01.parquet", index=False
    )

    tendencias = build_market_trends(tmp_path)
    fechas = [fila["fecha"] for fila in tendencias["Monte Castro"]]
    assert fechas == ["2026-01-01", "2026-01-02"]
