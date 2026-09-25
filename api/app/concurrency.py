"""Optimistic concurrency with strong ETags (§7.1, D6).

The ETag is the resource's integer `version`, quoted: `"3"`. Writes must send
`If-Match`. Comparison is strong (RFC 9110 §13.1.1), so a weak validator
(`W/"3"`) never matches, and nginx must never weaken our ETags.
"""

from app.problems import PreconditionFailed, PreconditionRequired


def etag(version: int) -> str:
    return f'"{version}"'


def check_if_match(if_match: str | None, current_version: int) -> None:
    """Raise 428 when If-Match is missing, 412 when it doesn't match."""
    if if_match is None or not if_match.strip():
        raise PreconditionRequired(
            "This request must include an If-Match header with the resource's current ETag, "
            'e.g. If-Match: "1".'
        )
    current = etag(current_version)
    candidates = [tag.strip() for tag in if_match.split(",")]
    if "*" in candidates or current in candidates:
        return
    raise PreconditionFailed(
        f"The resource has changed (current ETag {current}). Fetch it again and retry."
    )
