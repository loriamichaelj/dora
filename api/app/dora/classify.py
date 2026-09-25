"""Pure functions: band classification and rounding (§7.8). No I/O."""

from decimal import ROUND_HALF_UP, Decimal

from app.dora.bands import Band, BandSet, Metric


def classify(band_set: BandSet, metric: Metric, value: float | None) -> Band | None:
    """The band for a metric value, or None when there is no value.

    Classification uses the unrounded value, so a figure displayed as 0.1429
    is still judged against 1/7 exactly."""
    if value is None:
        return None
    for band, compare, threshold in band_set.rules[metric]:
        if compare(value, threshold):
            return band
    return "low"


def _round_half_up(value: float, places: int) -> float:
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def round_hours(value: float | None) -> float | None:
    """Hours to 2 decimal places (half up, not banker's rounding)."""
    return None if value is None else _round_half_up(value, 2)


def round_rate(value: float | None) -> float | None:
    """Rates and ratios to 4 decimal places (half up)."""
    return None if value is None else _round_half_up(value, 4)


def ratio(numerator: int, denominator: int) -> float | None:
    """numerator / denominator, or None for an empty denominator: zero
    deployments must never look like a 0% fail rate (§3)."""
    return None if denominator == 0 else numerator / denominator
