import pytest

from ingest.normalize import check_parse_rate, normalize_listing


def test_price_ars_converted_to_usd_with_mep_rate(mep, extracted_factory):
    record = extracted_factory(price_amount=150_000_000.0, price_currency="ARS")
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["price_usd"] == pytest.approx(150_000_000.0 / mep.rate)
    assert row["fx_rate_used"] == mep.rate
    assert row["fx_source"] == mep.source


def test_price_usd_native_passthrough_still_stamps_fx(mep, extracted_factory):
    record = extracted_factory(price_amount=130_000.0, price_currency="USD")
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["price_usd"] == 130_000.0
    assert row["fx_rate_used"] == mep.rate
    assert row["fx_source"] == mep.source


def test_missing_m2_cubiertos_stays_null_not_imputed(mep, extracted_factory):
    record = extracted_factory(m2_cubiertos=None)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["m2_cubiertos"] is None
    assert row["usd_m2"] is None  # no se puede derivar sin superficie, y no se imputa


def test_precio_a_consultar_excluded_from_price_but_row_kept(mep, extracted_factory):
    record = extracted_factory(price_amount=None, price_currency=None)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["price_usd"] is None
    assert row["portal_id"] == record["portal_id"]  # la fila se conserva para tracking


def test_outlier_usd_m2_flagged_not_deleted(mep, extracted_factory):
    record = extracted_factory(price_amount=90_000_000.0, price_currency="ARS", m2_cubiertos=9.0)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["price_usd"] == pytest.approx(90_000.0)
    assert row["usd_m2"] == pytest.approx(10_000.0)
    assert row["es_outlier"] is True
    assert row["outlier_reason"] is not None


def test_normal_usd_m2_not_flagged(mep, extracted_factory):
    record = extracted_factory(price_amount=130_000_000.0, price_currency="ARS", m2_cubiertos=72.0)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["es_outlier"] is False
    assert row["outlier_reason"] is None


def test_price_below_floor_flagged_even_without_m2(mep, extracted_factory):
    # Sin m2_cubiertos (típico de Zonaprop) el chequeo de usd_m2 nunca
    # corre — este es el único que puede atrapar un precio absurdo ahí.
    record = extracted_factory(price_amount=105_000.0, price_currency="ARS", m2_cubiertos=None)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000, price_usd_min=5000)
    assert row["price_usd"] < 5000
    assert row["es_outlier"] is True
    assert "price_usd" in row["outlier_reason"]


def test_price_above_floor_not_flagged(mep, extracted_factory):
    record = extracted_factory(price_amount=130_000.0, price_currency="USD", m2_cubiertos=None)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000, price_usd_min=5000)
    assert row["es_outlier"] is False
    assert row["outlier_reason"] is None


def test_expensas_stored_as_ars_not_converted(mep, extracted_factory):
    record = extracted_factory(expensas_ars=60_000.0)
    row = normalize_listing(record, mep, usd_m2_min=400, usd_m2_max=8000)
    assert row["expensas_ars"] == 60_000.0  # nunca se convierte a USD


def test_pozo_vs_usado_categorized(mep, extracted_factory):
    usado = normalize_listing(extracted_factory(condicion="usado"), mep, usd_m2_min=400, usd_m2_max=8000)
    pozo = normalize_listing(extracted_factory(condicion="pozo"), mep, usd_m2_min=400, usd_m2_max=8000)
    assert usado["condicion"] == "usado"
    assert pozo["condicion"] == "pozo"


def test_parse_failure_rate_triggers_loud_failure(mep, extracted_factory):
    rows = [
        normalize_listing(extracted_factory(portal_id=f"MLA{i}", price_amount=None, price_currency=None), mep, 400, 8000)
        for i in range(8)
    ] + [
        normalize_listing(extracted_factory(portal_id=f"MLA{i}"), mep, 400, 8000)
        for i in range(8, 10)
    ]
    # 2/10 = 20% con precio -> muy por debajo del 90% requerido
    with pytest.raises(ValueError, match="Tasa de parseo"):
        check_parse_rate(rows, field="price_usd", min_rate=0.9)


def test_parse_rate_ok_does_not_raise(mep, extracted_factory):
    rows = [normalize_listing(extracted_factory(portal_id=f"MLA{i}"), mep, 400, 8000) for i in range(10)]
    rate = check_parse_rate(rows, field="price_usd", min_rate=0.9)
    assert rate == 1.0
