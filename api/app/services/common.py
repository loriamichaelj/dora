from typing import Any, Protocol

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession


class Versioned(Protocol):
    version: Any
    updated_at: Any


def apply_changes(obj: object, changes: dict[str, Any]) -> bool:
    """Set each changed attribute. Returns True if anything actually changed,
    so a no-op PATCH leaves version and updated_at alone (§6.3)."""
    changed = False
    for field, value in changes.items():
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed = True
    return changed


async def save_changes(session: AsyncSession, obj: Versioned) -> None:
    """Bump the version and touch updated_at for an effective change."""
    obj.version = obj.version + 1
    obj.updated_at = func.now()
    await session.flush()
    await session.refresh(obj)
