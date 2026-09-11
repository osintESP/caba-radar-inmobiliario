import pandas as pd
import pytest

from ingest.price_events import append_events, detect_delistings, detect_price_changes


def _listing(portal_id, **overrides):
    base = {
        "portal": "meli",
        "portal_id": portal_id,
        "barrio": "Monte Castro",
        "tipo": "departamento",
        "price_usd": 130000.0,
        "url": f"https://x/{portal_id}",
        "titulo": "Depto test",
    }
    base.update(overrides)
    return base


def test_no_previous_snapshot_returns_empty(tmp_path):
    current = pd.DataFrame([_listing("A")])
    result = detect_delistings(current, tmp_path, tmp_path / "2026-01-02.parquet", "2026-01-02")
    assert result.empty


def test_listing_missing_today_is_detected_as_delisted(tmp_path):
    previous = pd.DataFrame([_listing("A"), _listing("B")])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A")])  # "B" desapareció
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_delistings(current, tmp_path, current_path, "2026-01-02")

    assert len(result) == 1
    assert result.iloc[0]["portal_id"] == "B"
    assert result.iloc[0]["event_type"] == "delisted"
    assert result.iloc[0]["event_at"] == "2026-01-02"


def test_nothing_missing_returns_empty(tmp_path):
    previous = pd.DataFrame([_listing("A")])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A")])
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_delistings(current, tmp_path, current_path, "2026-01-02")
    assert result.empty


def test_append_events_accumulates_across_runs(tmp_path):
    events_path = tmp_path / "price_events.parquet"

    day1 = pd.DataFrame([_listing("A", event_type="delisted", event_at="2026-01-01")])
    combined1 = append_events(day1, events_path)
    assert len(combined1) == 1

    day2 = pd.DataFrame([_listing("B", event_type="delisted", event_at="2026-01-02")])
    combined2 = append_events(day2, events_path)
    assert len(combined2) == 2  # se acumula, no se pisa

    reloaded = pd.read_parquet(events_path)
    assert set(reloaded["portal_id"]) == {"A", "B"}


def test_append_events_is_idempotent_for_same_day_rerun(tmp_path):
    events_path = tmp_path / "price_events.parquet"
    day1 = pd.DataFrame([_listing("A", event_type="delisted", event_at="2026-01-01")])
    append_events(day1, events_path)
    combined = append_events(day1, events_path)  # misma corrida repetida
    assert len(combined) == 1  # no duplica


def test_no_previous_snapshot_returns_empty_for_price_changes(tmp_path):
    current = pd.DataFrame([_listing("A")])
    result = detect_price_changes(current, tmp_path, tmp_path / "2026-01-02.parquet", "2026-01-02")
    assert result.empty


def test_price_drop_is_detected_as_price_change(tmp_path):
    previous = pd.DataFrame([_listing("A", price_usd=130000.0)])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A", price_usd=120000.0)])
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_price_changes(current, tmp_path, current_path, "2026-01-02")

    assert len(result) == 1
    row = result.iloc[0]
    assert row["event_type"] == "price_change"
    assert row["old_price_usd"] == 130000.0
    assert row["new_price_usd"] == 120000.0
    assert row["pct_change"] == pytest.approx(-100 * 10000 / 130000)


def test_price_raise_has_positive_pct_change(tmp_path):
    previous = pd.DataFrame([_listing("A", price_usd=100000.0)])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A", price_usd=110000.0)])
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_price_changes(current, tmp_path, current_path, "2026-01-02")

    assert len(result) == 1
    assert result.iloc[0]["pct_change"] == pytest.approx(10.0)


def test_same_price_is_not_a_price_change(tmp_path):
    previous = pd.DataFrame([_listing("A", price_usd=130000.0)])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A", price_usd=130000.0)])
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_price_changes(current, tmp_path, current_path, "2026-01-02")
    assert result.empty


def test_delisted_listing_has_no_price_change_row(tmp_path):
    # "B" desaparece: no está en current_df, así que no puede compararse
    # (eso lo cubre detect_delistings, no detect_price_changes).
    previous = pd.DataFrame([_listing("A", price_usd=130000.0), _listing("B", price_usd=100000.0)])
    previous_path = tmp_path / "2026-01-01.parquet"
    previous.to_parquet(previous_path, index=False)

    current = pd.DataFrame([_listing("A", price_usd=130000.0)])
    current_path = tmp_path / "2026-01-02.parquet"

    result = detect_price_changes(current, tmp_path, current_path, "2026-01-02")
    assert result.empty
