"""Business rules for Services (§6.3, §7.3)."""

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.concurrency import check_if_match
from app.models import Service
from app.problems import Conflict, NotFound, Unprocessable, field_error
from app.repositories import commits as commits_repo
from app.repositories import services as repo
from app.schemas.common import parse_sort
from app.schemas.services import ServiceCreate, ServiceUpdate
from app.services.common import apply_changes, save_changes

log = structlog.get_logger(__name__)

SORT_FIELDS = tuple(repo.SORT_COLUMNS)


async def list_page(
    session: AsyncSession,
    *,
    owner_team: str | None,
    q: str | None,
    sort: str,
    limit: int,
    offset: int,
) -> tuple[list[Service], int]:
    field, descending = parse_sort(sort)
    return await repo.list_page(
        session,
        owner_team=owner_team,
        q=q,
        sort_field=field,
        descending=descending,
        limit=limit,
        offset=offset,
    )


async def get(session: AsyncSession, service_id: uuid.UUID) -> Service:
    service = await repo.get(session, service_id)
    if service is None:
        raise NotFound(f"No service with id {service_id}.")
    return service


async def create(session: AsyncSession, data: ServiceCreate) -> Service:
    if await repo.get_by_slug(session, data.slug) is not None:
        raise Conflict(
            f"A service with slug {data.slug!r} already exists.",
            errors=[field_error("slug", "This slug is already in use.", type_="unique")],
        )
    service = Service(**data.model_dump())
    session.add(service)
    await session.flush()
    await session.refresh(service)
    await session.commit()
    return service


async def update(
    session: AsyncSession, service_id: uuid.UUID, patch: ServiceUpdate, if_match: str | None
) -> Service:
    service = await repo.get(session, service_id, for_update=True)
    if service is None:
        raise NotFound(f"No service with id {service_id}.")
    check_if_match(if_match, service.version)

    changes = patch.changes()
    slug = changes.pop("slug", None)
    if slug is not None and slug != service.slug:
        raise Unprocessable(
            "A service's slug cannot be changed after it is created.",
            errors=[field_error("slug", "slug is immutable", type_="immutable")],
        )
    if apply_changes(service, changes):
        await save_changes(session, service)
    await session.commit()
    return service


async def delete(session: AsyncSession, service_id: uuid.UUID, if_match: str | None) -> None:
    service = await repo.get(session, service_id, for_update=True)
    if service is None:
        raise NotFound(f"No service with id {service_id}.")
    check_if_match(if_match, service.version)
    deployments = await repo.count_deployments(session, service_id)
    if deployments:
        commits = await commits_repo.classify_for_service(session, service_id)
        raise Conflict(
            f"Service {service.slug!r} has {deployments} deployment(s) shipping "
            f"{commits.deployment_commits} deployment commit(s); delete the deployments first."
        )
    # With no deployments left, every remaining commit is a non-deployment
    # commit: nothing ships it and no metric reads it, so it goes with the service.
    removed = await commits_repo.delete_non_deployment_commits(session, service_id)
    await session.delete(service)
    await session.commit()
    log.info("service_deleted", slug=service.slug, non_deployment_commits_removed=removed)
