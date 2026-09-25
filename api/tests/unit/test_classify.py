"""Band classification, rounding, and window rules (§3, §7.8). Pure functions."""

from datetime import UTC, datetime, timedelta

import pytest

from app.dora.bands import BAND_SETS, DEFAULT_BAND_SET, Metric
from app.dora.classify import classify, ratio, round_hours, round_rate
from app.problems import Unprocessable
from app.services.metrics import resolve_window

BANDS = DEFAULT_BAND_SET


@pytest.mark.parametrize(
    ("metric", "value", "band"),
    [
        # deployments per day: >=1 elite, >=1/7 high, >=1/30 medium, else low
        ("deployment_frequency", 5.0, "elite"),
        ("deployment_frequency", 1.0, "elite"),
        ("deployment_frequency", 0.9999, "high"),
        ("deployment_frequency", 1 / 7, "high"),
        ("deployment_frequency", 4 / 30, "medium"),  # golden A: 0.1333 < 1/7
        ("deployment_frequency", 1 / 30, "medium"),
        ("deployment_frequency", 0.0333, "low"),
        # median lead hours: <24 elite, <168 high, <720 medium, else low
        ("change_lead_time", 0.0, "elite"),
        ("change_lead_time", 23.99, "elite"),
        ("change_lead_time", 24.0, "high"),
        ("change_lead_time", 167.99, "high"),
        ("change_lead_time", 168.0, "medium"),
        ("change_lead_time", 720.0, "low"),
        # fail rate: <=0.05 elite, <=0.10 high, <=0.15 medium, else low
        ("change_fail_rate", 0.0, "elite"),
        ("change_fail_rate", 0.05, "elite"),
        ("change_fail_rate", 0.0501, "high"),
        ("change_fail_rate", 0.10, "high"),
        ("change_fail_rate", 0.15, "medium"),
        ("change_fail_rate", 0.1501, "low"),
        ("change_fail_rate", 0.5, "low"),
        # median recovery hours: <1 elite, <24 high, <168 medium, else low
        ("failed_deployment_recovery_time", 0.5, "elite"),
        ("failed_deployment_recovery_time", 1.0, "high"),
        ("failed_deployment_recovery_time", 2.0, "high"),
        ("failed_deployment_recovery_time", 24.0, "medium"),
        ("failed_deployment_recovery_time", 168.0, "low"),
    ],
)
def test_band_boundaries(metric: Metric, value: float, band: str) -> None:
    assert classify(BANDS, metric, value) == band


@pytest.mark.parametrize("metric", list(DEFAULT_BAND_SET.rules))
def test_no_value_means_no_band(metric: Metric) -> None:
    assert classify(BANDS, metric, None) is None


def test_band_sets_are_labeled_with_a_source() -> None:
    assert BAND_SETS["dora-2023-adapted"] is DEFAULT_BAND_SET
    assert "DORA" in DEFAULT_BAND_SET.source
    # No rework bands and no overall band exist (D9).
    assert set(DEFAULT_BAND_SET.rules) == {
        "deployment_frequency",
        "change_lead_time",
        "change_fail_rate",
        "failed_deployment_recovery_time",
    }


@pytest.mark.parametrize(
    ("value", "hours", "rate"),
    [
        (0.125, 0.13, 0.125),  # half up, not banker's rounding (which gives 0.12)
        (2 / 3, 0.67, 0.6667),
        (4 / 30, 0.13, 0.1333),
        (19.0, 19.0, 19.0),
        (0.00005, 0.0, 0.0001),
    ],
)
def test_rounding(value: float, hours: float, rate: float) -> None:
    assert round_hours(value) == hours
    assert round_rate(value) == rate


def test_rounding_and_ratio_pass_none_through() -> None:
    assert round_hours(None) is None
    assert round_rate(None) is None
    assert ratio(0, 0) is None  # zero deployments is "no data", never 0%
    assert ratio(0, 4) == 0.0
    assert ratio(1, 4) == 0.25


NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)


def test_default_window_is_30_days_ending_now() -> None:
    assert resolve_window(None, None, now=NOW) == (NOW - timedelta(days=30), NOW)
    end = NOW - timedelta(days=10)
    assert resolve_window(None, end, now=NOW) == (end - timedelta(days=30), end)


def test_window_is_normalized_to_utc() -> None:
    start, _ = resolve_window(datetime.fromisoformat("2026-09-01T02:00:00+02:00"), NOW)
    assert start == datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    assert start.tzinfo is UTC


def test_window_limits() -> None:
    resolve_window(NOW - timedelta(days=365), NOW)  # exactly the max is fine
    with pytest.raises(Unprocessable):
        resolve_window(NOW - timedelta(days=365, seconds=1), NOW)
    with pytest.raises(Unprocessable):
        resolve_window(NOW, NOW)
    with pytest.raises(Unprocessable):
        resolve_window(NOW + timedelta(days=1), NOW)
