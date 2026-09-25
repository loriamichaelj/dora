"""Deployment status transitions (§7.7). Pure functions, no I/O.

The same matrix serves both write paths. The only difference is how a move
*backwards* is treated: CRUD rejects it with 409, while ingest treats it as a
stale, out-of-order event and ignores it (D5), because CI retries and
out-of-order delivery are normal.
"""

from enum import StrEnum
from typing import Literal

Status = Literal["in_progress", "succeeded", "failed", "rolled_back"]
Via = Literal["crud", "ingest"]


class Outcome(StrEnum):
    NOOP = "noop"  # same -> same
    APPLY = "apply"  # a valid forward move
    STALE = "stale"  # ingest only: an older event arriving late; ignore it
    CONFLICT = "conflict"  # a genuine contradiction; 409


# Forward moves allowed on both paths.
_FORWARD: frozenset[tuple[Status, Status]] = frozenset(
    {
        ("in_progress", "succeeded"),
        ("in_progress", "failed"),
        ("succeeded", "rolled_back"),
    }
)

# Moves that can only come from an older event: ingest ignores them.
_BACKWARD: frozenset[tuple[Status, Status]] = frozenset(
    {
        ("succeeded", "in_progress"),
        ("failed", "in_progress"),
        ("rolled_back", "in_progress"),
        ("rolled_back", "succeeded"),
    }
)

TERMINAL: frozenset[Status] = frozenset({"succeeded", "failed", "rolled_back"})


def evaluate(current: Status, requested: Status, via: Via) -> Outcome:
    if current == requested:
        return Outcome.NOOP
    if (current, requested) in _FORWARD:
        return Outcome.APPLY
    if (current, requested) in _BACKWARD and via == "ingest":
        return Outcome.STALE
    return Outcome.CONFLICT


def describe_conflict(current: Status, requested: Status) -> str:
    allowed = sorted(to for (frm, to) in _FORWARD if frm == current)
    options = ", ".join(allowed) if allowed else "none (final state)"
    return (
        f"A deployment cannot move from {current!r} to {requested!r}. "
        f"Allowed from {current!r}: {options}."
    )
