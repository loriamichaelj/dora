import uuid

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Commit, Deployment, Service
from app.repositories.base import escape_like, paginate

SORT_COLUMNS = {"name": Service.name, "created_at": Service.created_at}


async def get(
    session: AsyncSession, service_id: uuid.UUID, *, for_update: bool = False
) -> Service | None:
    stmt = select(Service).where(Service.id == service_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def get_by_slug(session: AsyncSession, slug: str) -> Service | None:
    return await session.scalar(select(Service).where(Service.slug == slug))


async def list_page(
    session: AsyncSession,
    *,
    owner_team: str | None,
    q: str | None,
    sort_field: str,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[list[Service], int]:
    stmt = select(Service)
    if owner_team is not None:
        stmt = stmt.where(Service.owner_team == owner_team)
    if q:
        pattern = f"%{escape_like(q)}%"
        stmt = stmt.where(or_(Service.slug.ilike(pattern), Service.name.ilike(pattern)))
    column = SORT_COLUMNS[sort_field]
    stmt = stmt.order_by(column.desc() if descending else column.asc(), Service.id)
    rows, total = await paginate(session, stmt, limit=limit, offset=offset)
    return [row[0] for row in rows], total


async def has_dependents(session: AsyncSession, service_id: uuid.UUID) -> bool:
    deployments = exists().where(Deployment.service_id == service_id)
    commits = exists().where(Commit.service_id == service_id)
    return bool(await session.scalar(select(or_(deployments, commits))))
