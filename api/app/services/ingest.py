"""Ingest of pipeline deployment events (§7.6, D5).

Idempotent upsert on (service, external_id):
- no deployment yet  -> create it (201)
- one exists         -> apply the event through the §7.7 matrix with via="ingest" (200)
  - identical replay -> nothing changes, no version bump
  - older event      -> ignored entirely, flagged `stale_event`
  - contradiction    -> 409
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deployment
from app.problems import Conflict, Unprocessable, field_error
from app.repositories import deployments as deployments_repo
from app.repositories import services as services_repo
from app.schemas.deployments import DeploymentCreate
from app.schemas.ingest import DeploymentEvent
from app.services import deployments as deployment_rules
from app.services.deployments import DeploymentView

EXTERNAL_ID_CONSTRAINT = "uq_service_external"


@dataclass(frozen=True)
class IngestOutcome:
    view: DeploymentView
    created: bool
    stale: bool


def _is_external_id_race(exc: Exception) -> bool:
    """True when another delivery of the same new event created the row first:
    either it committed before our duplicate check (Conflict on external_id)
    or during our INSERT (unique violation on uq_service_external)."""
    if isinstance(exc, Conflict):
        return any(e.field == "external_id" for e in exc.errors or [])
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) == EXTERNAL_ID_CONSTRAINT


async def _update(
    session: AsyncSession, deployment: Deployment, event: DeploymentEvent
) -> IngestOutcome:
    changes = event.model_dump(exclude_unset=True, exclude={"service_slug", "commits"})
    changes["commits"] = event.commits
    result = await deployment_rules.apply_update(session, deployment, changes, via="ingest")
    view = await deployment_rules.view(session, deployment)
    await session.commit()
    return IngestOutcome(view=view, created=False, stale=result.stale)


async def ingest(session: AsyncSession, event: DeploymentEvent) -> IngestOutcome:
    service = await services_repo.get_by_slug(session, event.service_slug)
    if service is None:
        # Never auto-create: a pipeline typo must not create a junk service.
        raise Unprocessable(
            f"No service with slug {event.service_slug!r}. Create it first.",
            errors=[field_error("service_slug", "Unknown service.", type_="not_found")],
        )

    existing = await deployments_repo.get_by_external_id(
        session, service.id, event.external_id, for_update=True
    )
    if existing is not None:
        return await _update(session, existing, event)

    data = DeploymentCreate(
        service_id=service.id,
        **event.model_dump(exclude={"service_slug", "commits"}),
        commits=event.commits,
    )
    try:
        async with session.begin_nested():
            deployment = await deployment_rules.insert(session, data)
    except (IntegrityError, Conflict) as exc:
        # Two deliveries of a new event raced; the other one inserted first.
        # Treat this one as an update of that row.
        if not _is_external_id_race(exc):
            raise
        existing = await deployments_repo.get_by_external_id(
            session, service.id, event.external_id, for_update=True
        )
        assert existing is not None
        return await _update(session, existing, event)

    view = await deployment_rules.view(session, deployment)
    await session.commit()
    return IngestOutcome(view=view, created=True, stale=False)
