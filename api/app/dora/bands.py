"""Benchmark band sets (§3, D9).

DORA's 2025 report replaced performance tiers with team archetypes, and the
2024 clusters aren't monotonic per metric, so bands here are an informational
aid only: configurable, labeled with their source, and never combined into an
overall grade. Rework rate has no published bands.

A rule is (band, operator, threshold). Rules are checked in order and the
first match wins; a value matching none of them is "low".
"""

import operator
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Band = Literal["elite", "high", "medium", "low"]
Metric = Literal[
    "deployment_frequency",
    "change_lead_time",
    "change_fail_rate",
    "failed_deployment_recovery_time",
]

GE: Callable[[float, float], bool] = operator.ge
LT: Callable[[float, float], bool] = operator.lt
LE: Callable[[float, float], bool] = operator.le

Rule = tuple[Band, Callable[[float, float], bool], float]

HOURS_PER_DAY = 24
HOURS_PER_WEEK = 7 * HOURS_PER_DAY
HOURS_PER_MONTH = 30 * HOURS_PER_DAY


@dataclass(frozen=True)
class BandSet:
    name: str
    source: str
    rules: dict[Metric, tuple[Rule, ...]]


DORA_2023_ADAPTED = BandSet(
    name="dora-2023-adapted",
    source=(
        "Adapted from the DORA 2023 Accelerate State of DevOps performance clusters; "
        "informational only, not for cross-team comparison."
    ),
    rules={
        # deployments per day: higher is better
        "deployment_frequency": (
            ("elite", GE, 1.0),
            ("high", GE, 1 / 7),
            ("medium", GE, 1 / 30),
        ),
        # median hours from commit to first live deployment: lower is better
        "change_lead_time": (
            ("elite", LT, HOURS_PER_DAY),
            ("high", LT, HOURS_PER_WEEK),
            ("medium", LT, HOURS_PER_MONTH),
        ),
        # ratio 0-1: lower is better
        "change_fail_rate": (
            ("elite", LE, 0.05),
            ("high", LE, 0.10),
            ("medium", LE, 0.15),
        ),
        # median hours from detection to resolution: lower is better
        "failed_deployment_recovery_time": (
            ("elite", LT, 1.0),
            ("high", LT, HOURS_PER_DAY),
            ("medium", LT, HOURS_PER_WEEK),
        ),
    },
)

BAND_SETS: dict[str, BandSet] = {DORA_2023_ADAPTED.name: DORA_2023_ADAPTED}
DEFAULT_BAND_SET = DORA_2023_ADAPTED
