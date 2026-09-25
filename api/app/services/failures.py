"""Business rules for Failures (§6.3, §7.5)."""

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.concurrency import check_if_match
from app.models import Failure
from app.models.entities import LIVE_STATUSES
from app.problems import Conflict, NotFound, Unprocessable, field_error
from app.repositories import deployments as deployments_repo
from app.repositories import failures as repo
from app.schemas.common import parse_sort
from app.schemas.failures import FailureCreate, FailureUpdate
from app.services.common import apply_changes, save_changes

SORT_FIELDS = tuple(repo.SORT_COLUMNS)


async def _validate(
    session: AsyncSession,
    deployment_id: uuid.UUID,
    detected_at: datetime,
    resolved_at: datetime | None,
) -> uuid.UUID:
    """Enforce the §6.3 failure rules. Returns the deployment's service_id."""
    deployment = await deployments_repo.get(session, deployment_id)
    if deployment is None:
        raise Unprocessable(
            f"No deployment with id {deployment_id}.",
            errors=[field_error("deployment_id", "No deployment with this id.", type_="not_found")],
        )
    if deployment.status not in LIVE_STATUSES:
        raise Conflict(
            "A failure can only reference a live deployment (succeeded or rolled_back); "
            f"deployment {deployment_id} is {deployment.status!r}."
        )
    assert deployment.finished_at is not None  # live deployments always have one
    if detected_at < deployment.finished_at:
        raise Unprocessable(
            "A failure cannot be detected before its deployment finished.",
            errors=[
                field_error(
                    "detected_at",
                    f"Must be at or after the deployment's finished_at "
                    f"({deployment.finished_at.isoformat()}).",
                    type_="before_deployment",
                )
            ],
        )
    if resolved_at is not None and resolved_at < detected_at:
        raise Unprocessable(
            "A failure cannot be resolved before it was detected.",
            errors=[
                field_error(
                    "resolved_at", "Must be at or after detected_at.", type_="before_detected"
                )
            ],
        )
    return deployment.service_id


async def list_page(
    session: AsyncSession,
    *,
    service_id: uuid.UUID | None,
    deployment_id: uuid.UUID | None,
    severity: str | None,
    is_open: bool | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Failure, uuid.UUID]], int]:
    field, descending = parse_sort(sort)
    return await repo.list_page(
        session,
        service_id=service_id,
        deployment_id=deployment_id,
        severity=severity,
        is_open=is_open,
        sort_field=field,
        descending=descending,
        limit=limit,
        offset=offset,
    )


async def get(session: AsyncSession, failure_id: uuid.UUID) -> tuple[Failure, uuid.UUID]:
    found = await repo.get(session, failure_id)
    if found is None:
        raise NotFound(f"No failure with id {failure_id}.")
    return found


async def create(session: AsyncSession, data: FailureCreate) -> tuple[Failure, uuid.UUID]:
    service_id = await _validate(session, data.deployment_id, data.detected_at, data.resolved_at)
    failure = Failure(**data.model_dump())
    session.add(failure)
    await session.flush()
    await session.refresh(failure)
    await session.commit()
    return failure, service_id


async def update(
    session: AsyncSession, failure_id: uuid.UUID, patch: FailureUpdate, if_match: str | None
) -> tuple[Failure, uuid.UUID]:
    found = await repo.get(session, failure_id, for_update=True)
    if found is None:
        raise NotFound(f"No failure with id {failure_id}.")
    failure, service_id = found
    check_if_match(if_match, failure.version)

    changes = patch.changes()
    if changes.keys() & {"deployment_id", "detected_at", "resolved_at"}:
        service_id = await _validate(
            session,
            changes.get("deployment_id", failure.deployment_id),
            changes.get("detected_at", failure.detected_at),
            changes.get("resolved_at", failure.resolved_at),
        )
    if apply_changes(failure, changes):
        await save_changes(session, failure)
    await session.commit()
    return failure, service_id


async def delete(session: AsyncSession, failure_id: uuid.UUID, if_match: str | None) -> None:
    found = await repo.get(session, failure_id, for_update=True)
    if found is None:
        raise NotFound(f"No failure with id {failure_id}.")
    failure, _ = found
    check_if_match(if_match, failure.version)
    await session.delete(failure)
    await session.commit()
