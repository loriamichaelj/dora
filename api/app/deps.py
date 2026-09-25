"""Shared FastAPI dependencies."""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.common import DEFAULT_LIMIT, MAX_LIMIT


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    # Services commit explicitly; anything uncommitted is rolled back on close.
    async with request.app.state.sessionmaker() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]
IfMatch = Annotated[
    str | None,
    Header(alias="If-Match", description='Current ETag, e.g. "3". Required for writes.'),
]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size")]
Offset = Annotated[int, Query(ge=0, description="Items to skip")]

__all__ = ["DEFAULT_LIMIT", "IfMatch", "Limit", "Offset", "Session"]
