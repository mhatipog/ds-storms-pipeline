"""Regression coverage for issue OCHA-DAP/ds-storms-pipeline#20.

No live NHC feed, database connection or cloud service is needed.
"""
from datetime import datetime, timedelta

from src.pipelines.nhc_obsv_lookup import (
    index_obsv_times,
    latest_obsv_at_or_before,
)


def dt(hour, minute=0):
    return datetime(2026, 8, 15, hour, minute)


def test_special_advisory_between_exact_probes_is_not_dropped():
    # Old logic checked WSP time (15:00) and +3h (18:00) *only*.
    lookup = {("AL01", dt(16, 30), 34): "correct_swath"}
    assert latest_obsv_at_or_before(
        index_obsv_times(lookup), lookup, "AL01", 34,
        dt(15) + timedelta(hours=3),
    ) == (dt(16, 30), "correct_swath")


def test_latest_eligible_observation_wins_and_future_is_excluded():
    lookup = {
        ("AL01", dt(14), 34): "old",
        ("AL01", dt(16, 30), 34): "latest",
        ("AL01", dt(18), 34): "at_boundary",
        ("AL01", dt(19), 34): "future",
    }
    index = index_obsv_times(lookup)
    assert latest_obsv_at_or_before(index, lookup, "AL01", 34, dt(17)) == (
        dt(16, 30), "latest"
    )
    assert latest_obsv_at_or_before(index, lookup, "AL01", 34, dt(18)) == (
        dt(18), "at_boundary"
    )


def test_no_eligible_observation_preserves_no_obsv_fallback():
    lookup = {("AL01", dt(19), 34): "future"}
    assert latest_obsv_at_or_before(
        index_obsv_times(lookup), lookup, "AL01", 34, dt(18)
    ) == (None, None)
    assert latest_obsv_at_or_before({}, {}, "AL01", 34, dt(18)) == (None, None)


def test_storms_and_wind_thresholds_do_not_cross_match():
    lookup = {
        ("AL02", dt(16), 34): "other_storm",
        ("AL01", dt(16), 50): "other_speed",
        ("AL01", dt(14), 34): "correct",
    }
    assert latest_obsv_at_or_before(
        index_obsv_times(lookup), lookup, "AL01", 34, dt(18)
    ) == (dt(14), "correct")


def test_lookup_does_not_modify_input():
    lookup = {("AL01", dt(18), 34): "new", ("AL01", dt(14), 34): "old"}
    original = lookup.copy()
    index = index_obsv_times(lookup)
    assert index[("AL01", 34)] == [dt(14), dt(18)]
    assert lookup == original


def test_special_advisory_changes_actual_wsp_cutout_area():
    from shapely.geometry import box
    wsp = box(0, 0, 4, 4)
    lookup = {("AL01", dt(16, 30), 34): box(0, 0, 2, 4)}
    valid_time, obsv = latest_obsv_at_or_before(
        index_obsv_times(lookup), lookup, "AL01", 34, dt(18)
    )
    assert valid_time == dt(16, 30)
    assert wsp.difference(obsv).area == 8
    assert wsp.area == 16


def test_pandas_timestamps_match_database_lookup_types():
    import pandas as pd
    issue = pd.Timestamp("2026-08-15 15:00:00")
    observed = pd.Timestamp("2026-08-15 16:30:00")
    lookup = {("AL01", observed, 34): "observed"}
    assert latest_obsv_at_or_before(
        index_obsv_times(lookup), lookup, "AL01", 34,
        issue + timedelta(hours=3),
    ) == (observed, "observed")
