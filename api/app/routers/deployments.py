"""/api/v1/deployments (§7.4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from pydantic import AwareDatetime

from app.concurrency import etag
from app.deps import DEFAULT_LIMIT, IfMatch, Limit, Offset, Session
from app.problems import problem_responses
from app.schemas.common import Page, sort_pattern
from app.schemas.deployments import (
    CommitOut,
    DeploymentCreate,
    DeploymentDetail,
    DeploymentOut,
    DeploymentUpdate,
    Environment,
    FailureSummary,
    Kind,
)
from app.services import deployments as deployment_rules
from app.services.deployments import DeploymentView
from app.services.transitions import Status

router = APIRouter(prefix="/deployments", tags=["deployments"])

SortDeployments = Annotated[str, Query(pattern=sort_pattern(*deployment_rules.SORT_FIELDS))]


def to_detail(found: DeploymentView) -> DeploymentDetail:
    base = DeploymentOut.model_validate(found.deployment)
    return DeploymentDetail(
        **base.model_dump(),
        commits=[CommitOut.model_validate(c) for c in found.commits],
        failures=[FailureSummary.model_validate(f) for f in found.failures],
    )


def _out(response: Response, found: DeploymentView) -> DeploymentDetail:
    out = to_detail(found)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("", response_model=Page[DeploymentOut], responses=problem_responses())
async def list_deployments(
    session: Session,
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    environment: Annotated[Environment | None, Query()] = None,
    status: Annotated[Status | None, Query()] = None,
    kind: Annotated[Kind | None, Query()] = None,
    from_: Annotated[
        AwareDatetime | None, Query(alias="from", description="started_at >= from (inclusive)")
    ] = None,
    to: Annotated[AwareDatetime | None, Query(description="started_at < to (exclusive)")] = None,
    sort: SortDeployments = "-started_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> Page[DeploymentOut]:
    items, total = await deployment_rules.list_page(
        session,
        service_id=service_id,
        environment=environment,
        status=status,
        kind=kind,
        started_from=from_,
        started_to=to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[DeploymentOut.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DeploymentDetail,
    responses=problem_responses(409),
)
async def create_deployment(
    body: DeploymentCreate, session: Session, response: Response
) -> DeploymentDetail:
    found = await deployment_rules.create(session, body)
    response.headers["Location"] = f"/api/v1/deployments/{found.deployment.id}"
    return _out(response, found)


@router.get("/{deployment_id}", response_model=DeploymentDetail, responses=problem_responses(404))
async def get_deployment(
    deployment_id: uuid.UUID, session: Session, response: Response
) -> DeploymentDetail:
    return _out(response, await deployment_rules.get(session, deployment_id))


@router.patch(
    "/{deployment_id}",
    response_model=DeploymentDetail,
    responses=problem_responses(404, 409, 412, 428),
)
async def update_deployment(
    deployment_id: uuid.UUID,
    body: DeploymentUpdate,
    session: Session,
    response: Response,
    if_match: IfMatch = None,
) -> DeploymentDetail:
    return _out(response, await deployment_rules.update(session, deployment_id, body, if_match))


@router.delete(
    "/{deployment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(404, 409, 412, 428),
)
async def delete_deployment(
    deployment_id: uuid.UUID, session: Session, if_match: IfMatch = None
) -> None:
    await deployment_rules.delete(session, deployment_id, if_match)
