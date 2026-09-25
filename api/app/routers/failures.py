"""/api/v1/failures (§7.5)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.concurrency import etag
from app.deps import DEFAULT_LIMIT, IfMatch, Limit, Offset, Session
from app.models import Failure
from app.problems import problem_responses
from app.schemas.common import Page, sort_pattern
from app.schemas.failures import FailureCreate, FailureOut, FailureUpdate, Severity
from app.services import failures as failure_rules

router = APIRouter(prefix="/failures", tags=["failures"])

SortFailures = Annotated[str, Query(pattern=sort_pattern(*failure_rules.SORT_FIELDS))]


def to_out(failure: Failure, service_id: uuid.UUID) -> FailureOut:
    return FailureOut(
        id=failure.id,
        deployment_id=failure.deployment_id,
        service_id=service_id,
        severity=failure.severity,
        summary=failure.summary,
        detected_at=failure.detected_at,
        resolved_at=failure.resolved_at,
        external_ref=failure.external_ref,
        version=failure.version,
        created_at=failure.created_at,
        updated_at=failure.updated_at,
    )


def _out(response: Response, found: tuple[Failure, uuid.UUID]) -> FailureOut:
    out = to_out(*found)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("", response_model=Page[FailureOut], responses=problem_responses())
async def list_failures(
    session: Session,
    service_id: Annotated[uuid.UUID | None, Query()] = None,
    deployment_id: Annotated[uuid.UUID | None, Query()] = None,
    severity: Annotated[Severity | None, Query()] = None,
    open: Annotated[bool | None, Query(description="true: unresolved; false: resolved")] = None,
    sort: SortFailures = "-detected_at",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> Page[FailureOut]:
    rows, total = await failure_rules.list_page(
        session,
        service_id=service_id,
        deployment_id=deployment_id,
        severity=severity,
        is_open=open,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return Page(items=[to_out(*row) for row in rows], total=total, limit=limit, offset=offset)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FailureOut,
    responses=problem_responses(409),
)
async def create_failure(body: FailureCreate, session: Session, response: Response) -> FailureOut:
    found = await failure_rules.create(session, body)
    response.headers["Location"] = f"/api/v1/failures/{found[0].id}"
    return _out(response, found)


@router.get("/{failure_id}", response_model=FailureOut, responses=problem_responses(404))
async def get_failure(failure_id: uuid.UUID, session: Session, response: Response) -> FailureOut:
    return _out(response, await failure_rules.get(session, failure_id))


@router.patch(
    "/{failure_id}",
    response_model=FailureOut,
    responses=problem_responses(404, 409, 412, 428),
)
async def update_failure(
    failure_id: uuid.UUID,
    body: FailureUpdate,
    session: Session,
    response: Response,
    if_match: IfMatch = None,
) -> FailureOut:
    return _out(response, await failure_rules.update(session, failure_id, body, if_match))


@router.delete(
    "/{failure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(404, 412, 428),
)
async def delete_failure(failure_id: uuid.UUID, session: Session, if_match: IfMatch = None) -> None:
    await failure_rules.delete(session, failure_id, if_match)
