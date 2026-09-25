"""Business rules for Deployments (§6.3, §7.4, §7.7).

`create` and `apply_update` are shared by the CRUD API and the ingest endpoint
(M4); `via` selects how backward status moves are treated (see transitions).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.concurrency import check_if_match
from app.models import Commit, Deployment, Failure
from app.models.entities import LIVE_STATUSES
from app.problems import Conflict, NotFound, Unprocessable, field_error
from app.repositories import commits as commits_repo
from app.repositories import deployments as repo
from app.repositories import services as services_repo
from app.schemas.common import parse_sort
from app.schemas.deployments import CommitIn, DeploymentCreate, DeploymentUpdate
from app.services.common import apply_changes, save_changes
from app.services.transitions import TERMINAL, Outcome, Status, Via, describe_conflict, evaluate

log = structlog.get_logger(__name__)

SORT_FIELDS = tuple(repo.SORT_COLUMNS)
IMMUTABLE_FIELDS = ("service_id", "environment", "external_id")


@dataclass(frozen=True)
class DeploymentView:
    deployment: Deployment
    commits: list[Commit]
    failures: list[Failure]


@dataclass(frozen=True)
class UpdateResult:
    changed: bool
    stale: bool


def validate_timing(status: Status, started_at: datetime, finished_at: datetime | None) -> None:
    if finished_at is not None and finished_at < started_at:
        raise Unprocessable(
            "A deployment cannot finish before it started.",
            errors=[field_error("finished_at", "Must be at or after started_at.", type_="order")],
        )
    if status in TERMINAL and finished_at is None:
        raise Unprocessable(
            f"A {status!r} deployment must have finished_at.",
            errors=[
                field_error("finished_at", f"Required when status is {status!r}.", type_="missing")
            ],
        )
    if status == "in_progress" and finished_at is not None:
        raise Unprocessable(
            "An in_progress deployment cannot have finished_at.",
            errors=[
                field_error("finished_at", "Must be empty while in_progress.", type_="forbidden")
            ],
        )


async def attach_commits(
    session: AsyncSession, deployment: Deployment, commits: list[CommitIn]
) -> int:
    """Upsert commits by (service, sha) and link them. Returns the number of
    newly linked commits. An existing commit is never overwritten: if it's
    posted again with a different committed_at, the first write wins and we
    log both values, but the request still succeeds (§6.3)."""
    unique: dict[str, CommitIn] = {}
    for commit in commits:
        unique.setdefault(commit.sha, commit)
    if not unique:
        return 0
    stored = await commits_repo.upsert(
        session,
        deployment.service_id,
        [
            commits_repo.NewCommit(c.sha, c.committed_at, c.author, c.message)
            for c in unique.values()
        ],
    )
    for sha, incoming in unique.items():
        existing = stored[sha]
        if existing.committed_at != incoming.committed_at:
            log.warning(
                "commit_committed_at_conflict",
                service_id=str(deployment.service_id),
                sha=sha,
                kept=existing.committed_at.isoformat(),
                ignored=incoming.committed_at.isoformat(),
            )
    return await commits_repo.link(session, deployment.id, [c.id for c in stored.values()])


async def list_page(
    session: AsyncSession,
    *,
    service_id: uuid.UUID | None,
    environment: str | None,
    status: str | None,
    kind: str | None,
    started_from: datetime | None,
    started_to: datetime | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[Deployment], int]:
    field, descending = parse_sort(sort)
    return await repo.list_page(
        session,
        service_id=service_id,
        environment=environment,
        status=status,
        kind=kind,
        started_from=started_from,
        started_to=started_to,
        sort_field=field,
        descending=descending,
        limit=limit,
        offset=offset,
    )


async def view(session: AsyncSession, deployment: Deployment) -> DeploymentView:
    return DeploymentView(
        deployment=deployment,
        commits=await commits_repo.for_deployment(session, deployment.id),
        failures=await repo.failures_for(session, deployment.id),
    )


async def get(session: AsyncSession, deployment_id: uuid.UUID) -> DeploymentView:
    deployment = await repo.get(session, deployment_id)
    if deployment is None:
        raise NotFound(f"No deployment with id {deployment_id}.")
    return await view(session, deployment)


async def insert(session: AsyncSession, data: DeploymentCreate) -> Deployment:
    """Validate and insert (without committing). Shared with ingest."""
    if await services_repo.get(session, data.service_id) is None:
        raise Unprocessable(
            f"No service with id {data.service_id}.",
            errors=[field_error("service_id", "No service with this id.", type_="not_found")],
        )
    validate_timing(data.status, data.started_at, data.finished_at)
    if data.external_id is not None and (
        await repo.get_by_external_id(session, data.service_id, data.external_id) is not None
    ):
        raise Conflict(
            f"This service already has a deployment with external_id {data.external_id!r}.",
            errors=[field_error("external_id", "Already used for this service.", type_="unique")],
        )
    deployment = Deployment(**data.model_dump(exclude={"commits"}))
    session.add(deployment)
    await session.flush()
    await attach_commits(session, deployment, data.commits)
    await session.refresh(deployment)
    return deployment


async def create(session: AsyncSession, data: DeploymentCreate) -> DeploymentView:
    deployment = await insert(session, data)
    result = await view(session, deployment)
    await session.commit()
    return result


def _check_immutable(deployment: Deployment, changes: dict[str, Any]) -> None:
    errors = [
        field_error(name, f"{name} cannot be changed after create.", type_="immutable")
        for name in IMMUTABLE_FIELDS
        if name in changes and changes[name] != getattr(deployment, name)
    ]
    if errors:
        raise Unprocessable("Some fields are immutable after create.", errors=errors)
    for name in IMMUTABLE_FIELDS:
        changes.pop(name, None)


async def apply_update(
    session: AsyncSession, deployment: Deployment, changes: dict[str, Any], via: Via
) -> UpdateResult:
    """Apply a partial update to a locked deployment row (without committing).

    `changes` holds only the fields the caller sent. A stale ingest event
    changes nothing at all, not even the fields other than status."""
    _check_immutable(deployment, changes)
    commits: list[CommitIn] = changes.pop("commits", None) or []

    current: Status = deployment.status  # type: ignore[assignment]
    requested: Status = changes.get("status", current)
    outcome = evaluate(current, requested, via)
    if outcome is Outcome.STALE:
        return UpdateResult(changed=False, stale=True)
    if outcome is Outcome.CONFLICT:
        raise Conflict(describe_conflict(current, requested))

    status = requested
    started_at: datetime = changes.get("started_at", deployment.started_at)
    finished_at: datetime | None = changes.get("finished_at", deployment.finished_at)
    validate_timing(status, started_at, finished_at)

    if (
        "finished_at" in changes
        and finished_at != deployment.finished_at
        and finished_at is not None
        and status in LIVE_STATUSES
    ):
        earliest = await repo.earliest_failure_detected_at(session, deployment.id)
        if earliest is not None and earliest < finished_at:
            raise Conflict(
                "finished_at cannot move after a linked failure's detected_at "
                f"({earliest.isoformat()})."
            )

    changed = apply_changes(deployment, changes)
    new_links = await attach_commits(session, deployment, commits)
    if changed or new_links:
        await save_changes(session, deployment)
    return UpdateResult(changed=changed or new_links > 0, stale=False)


async def update(
    session: AsyncSession,
    deployment_id: uuid.UUID,
    patch: DeploymentUpdate,
    if_match: str | None,
) -> DeploymentView:
    deployment = await repo.get(session, deployment_id, for_update=True)
    if deployment is None:
        raise NotFound(f"No deployment with id {deployment_id}.")
    check_if_match(if_match, deployment.version)
    changes = patch.changes()
    if "commits" in changes:
        changes["commits"] = patch.commits
    await apply_update(session, deployment, changes, via="crud")
    result = await view(session, deployment)
    await session.commit()
    return result


async def delete(session: AsyncSession, deployment_id: uuid.UUID, if_match: str | None) -> None:
    deployment = await repo.get(session, deployment_id, for_update=True)
    if deployment is None:
        raise NotFound(f"No deployment with id {deployment_id}.")
    check_if_match(if_match, deployment.version)
    if await repo.has_failures(session, deployment_id):
        raise Conflict("This deployment has failures; delete them first.")
    await session.delete(deployment)
    await session.commit()
