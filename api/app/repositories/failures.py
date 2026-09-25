import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deployment, Failure
from app.repositories.base import paginate

SORT_COLUMNS = {"detected_at": Failure.detected_at, "created_at": Failure.created_at}


def _with_service() -> Select[Failure, uuid.UUID]:
    return select(Failure, Deployment.service_id).join(
        Deployment, Deployment.id == Failure.deployment_id
    )


async def get(
    session: AsyncSession, failure_id: uuid.UUID, *, for_update: bool = False
) -> tuple[Failure, uuid.UUID] | None:
    stmt = _with_service().where(Failure.id == failure_id)
    if for_update:
        stmt = stmt.with_for_update(of=Failure)
    row = (await session.execute(stmt)).first()
    return (row[0], row[1]) if row else None


async def list_page(
    session: AsyncSession,
    *,
    service_id: uuid.UUID | None,
    deployment_id: uuid.UUID | None,
    severity: str | None,
    is_open: bool | None,
    sort_field: str,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Failure, uuid.UUID]], int]:
    stmt = _with_service()
    if service_id is not None:
        stmt = stmt.where(Deployment.service_id == service_id)
    if deployment_id is not None:
        stmt = stmt.where(Failure.deployment_id == deployment_id)
    if severity is not None:
        stmt = stmt.where(Failure.severity == severity)
    if is_open is True:
        stmt = stmt.where(Failure.resolved_at.is_(None))
    elif is_open is False:
        stmt = stmt.where(Failure.resolved_at.is_not(None))
    column = SORT_COLUMNS[sort_field]
    stmt = stmt.order_by(column.desc() if descending else column.asc(), Failure.id)
    rows, total = await paginate(session, stmt, limit=limit, offset=offset)
    return [(row[0], row[1]) for row in rows], total
