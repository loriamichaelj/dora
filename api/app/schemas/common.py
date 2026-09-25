"""Shared API types: UTC timestamps, the page envelope, and sort parsing."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, PlainSerializer


def _to_utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Responses are always UTC with a `Z` suffix (§7.1).
UtcDatetime = Annotated[datetime, PlainSerializer(_to_utc_z, return_type=str, when_used="json")]

# Requests must carry an offset: a naive timestamp is ambiguous and rejected.
AwareTimestamp = AwareDatetime

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int


def parse_sort(value: str) -> tuple[str, bool]:
    """`-field` sorts descending. Returns (field, descending)."""
    return (value[1:], True) if value.startswith("-") else (value, False)


def sort_pattern(*fields: str) -> str:
    """Regex for a `sort` query parameter restricted to a whitelist (§7.1)."""
    return rf"^-?({'|'.join(fields)})$"
