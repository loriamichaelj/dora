"""The §7.7 transition matrix, exhaustively, for both write paths."""

import itertools
from datetime import UTC, datetime, timedelta

import pytest

from app.problems import Unprocessable
from app.services.deployments import validate_timing
from app.services.transitions import Outcome, Status, describe_conflict, evaluate

STATUSES: tuple[Status, ...] = ("in_progress", "succeeded", "failed", "rolled_back")

# (from, to) -> (CRUD outcome, ingest outcome). Every pair is listed, so a
# new rule can't slip in without this table changing.
N, A, S, C = Outcome.NOOP, Outcome.APPLY, Outcome.STALE, Outcome.CONFLICT
MATRIX: dict[tuple[Status, Status], tuple[Outcome, Outcome]] = {
    ("in_progress", "in_progress"): (N, N),
    ("in_progress", "succeeded"): (A, A),
    ("in_progress", "failed"): (A, A),
    ("in_progress", "rolled_back"): (C, C),
    ("succeeded", "in_progress"): (C, S),
    ("succeeded", "succeeded"): (N, N),
    ("succeeded", "failed"): (C, C),
    ("succeeded", "rolled_back"): (A, A),
    ("failed", "in_progress"): (C, S),
    ("failed", "succeeded"): (C, C),
    ("failed", "failed"): (N, N),
    ("failed", "rolled_back"): (C, C),
    ("rolled_back", "in_progress"): (C, S),
    ("rolled_back", "succeeded"): (C, S),
    ("rolled_back", "failed"): (C, C),
    ("rolled_back", "rolled_back"): (N, N),
}


def test_matrix_covers_every_pair() -> None:
    assert set(MATRIX) == set(itertools.product(STATUSES, STATUSES))


@pytest.mark.parametrize(("pair", "expected"), MATRIX.items(), ids=lambda v: str(v))
def test_transition(pair: tuple[Status, Status], expected: tuple[Outcome, Outcome]) -> None:
    current, requested = pair
    assert evaluate(current, requested, "crud") is expected[0]
    assert evaluate(current, requested, "ingest") is expected[1]


def test_conflict_message_names_both_states_and_options() -> None:
    message = describe_conflict("succeeded", "failed")
    assert "'succeeded'" in message
    assert "'failed'" in message
    assert "rolled_back" in message
    assert "final state" in describe_conflict("failed", "succeeded")


T0 = datetime(2026, 9, 20, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "finished_at", "ok"),
    [
        ("in_progress", None, True),
        ("in_progress", T0, False),
        ("succeeded", T0, True),
        ("succeeded", None, False),
        ("failed", None, False),
        ("rolled_back", T0 + timedelta(minutes=5), True),
        ("succeeded", T0 - timedelta(seconds=1), False),
    ],
)
def test_validate_timing(status: Status, finished_at: datetime | None, ok: bool) -> None:
    if ok:
        validate_timing(status, T0, finished_at)
    else:
        with pytest.raises(Unprocessable):
            validate_timing(status, T0, finished_at)
