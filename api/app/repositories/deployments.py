import uuid
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deployment, Failure
from app.repositories.base import paginate

SORT_COLUMNS = {"started_at": Deployment.started_at, "finished_at": Deployment.finished_at}


async def get(
    session: AsyncSession, deployment_id: uuid.UUID, *, for_update: bool = False
) -> Deployment | None:
    stmt = select(Deployment).where(Deployment.id == deployment_id)
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def get_by_external_id(
    session: AsyncSession, service_id: uuid.UUID, external_id: str, *, for_update: bool = False
) -> Deployment | None:
    stmt = select(Deployment).where(
        Deployment.service_id == service_id, Deployment.external_id == external_id
    )
    if for_update:
        stmt = stmt.with_for_update()
    return await session.scalar(stmt)


async def list_page(
    session: AsyncSession,
    *,
    service_id: uuid.UUID | None,
    environment: str | None,
    status: str | None,
    kind: str | None,
    started_from: datetime | None,
    started_to: datetime | None,
    sort_field: str,
    descending: bool,
    limit: int,
    offset: int,
) -> tuple[list[Deployment], int]:
    stmt = select(Deployment)
    if service_id is not None:
        stmt = stmt.where(Deployment.service_id == service_id)
    if environment is not None:
        stmt = stmt.where(Deployment.environment == environment)
    if status is not None:
        stmt = stmt.where(Deployment.status == status)
    if kind is not None:
        stmt = stmt.where(Deployment.kind == kind)
    if started_from is not None:
        stmt = stmt.where(Deployment.started_at >= started_from)
    if started_to is not None:
        stmt = stmt.where(Deployment.started_at < started_to)
    column = SORT_COLUMNS[sort_field]
    order = column.desc() if descending else column.asc()
    stmt = stmt.order_by(order.nulls_last(), Deployment.id.desc() if descending else Deployment.id)
    rows, total = await paginate(session, stmt, limit=limit, offset=offset)
    return [row[0] for row in rows], total


async def failures_for(session: AsyncSession, deployment_id: uuid.UUID) -> list[Failure]:
    stmt = (
        select(Failure)
        .where(Failure.deployment_id == deployment_id)
        .order_by(Failure.detected_at, Failure.id)
    )
    return list(await session.scalars(stmt))


async def has_failures(session: AsyncSession, deployment_id: uuid.UUID) -> bool:
    return bool(
        await session.scalar(select(exists().where(Failure.deployment_id == deployment_id)))
    )


async def earliest_failure_detected_at(
    session: AsyncSession, deployment_id: uuid.UUID
) -> datetime | None:
    return await session.scalar(
        select(Failure.detected_at)
        .where(Failure.deployment_id == deployment_id)
        .order_by(Failure.detected_at)
        .limit(1)
    )
