from sqlalchemy import Row, Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession


def escape_like(value: str) -> str:
    """Escape LIKE wildcards so user search text matches literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def paginate[*Ts](
    session: AsyncSession, stmt: Select[*Ts], *, limit: int, offset: int
) -> tuple[list[Row[*Ts]], int]:
    """Run a filtered, ordered SELECT for one page, plus its total count."""
    total = await session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
    return list(rows), int(total or 0)
