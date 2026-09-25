"""/api/v1/services (§7.3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from app.concurrency import etag
from app.deps import DEFAULT_LIMIT, IfMatch, Limit, Offset, Session
from app.problems import problem_responses
from app.schemas.common import Page, sort_pattern
from app.schemas.services import ServiceCreate, ServiceOut, ServiceUpdate
from app.services import services as service_rules

router = APIRouter(prefix="/services", tags=["services"])

SortServices = Annotated[str, Query(pattern=sort_pattern(*service_rules.SORT_FIELDS))]


def _out(response: Response, service: object) -> ServiceOut:
    out = ServiceOut.model_validate(service)
    response.headers["ETag"] = etag(out.version)
    return out


@router.get("", response_model=Page[ServiceOut], responses=problem_responses())
async def list_services(
    session: Session,
    owner_team: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(description="Slug or name contains")] = None,
    sort: SortServices = "name",
    limit: Limit = DEFAULT_LIMIT,
    offset: Offset = 0,
) -> Page[ServiceOut]:
    items, total = await service_rules.list_page(
        session, owner_team=owner_team, q=q, sort=sort, limit=limit, offset=offset
    )
    return Page(
        items=[ServiceOut.model_validate(s) for s in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceOut,
    responses=problem_responses(409),
)
async def create_service(body: ServiceCreate, session: Session, response: Response) -> ServiceOut:
    service = await service_rules.create(session, body)
    response.headers["Location"] = f"/api/v1/services/{service.id}"
    return _out(response, service)


@router.get("/{service_id}", response_model=ServiceOut, responses=problem_responses(404))
async def get_service(service_id: uuid.UUID, session: Session, response: Response) -> ServiceOut:
    return _out(response, await service_rules.get(session, service_id))


@router.patch(
    "/{service_id}",
    response_model=ServiceOut,
    responses=problem_responses(404, 412, 428),
)
async def update_service(
    service_id: uuid.UUID,
    body: ServiceUpdate,
    session: Session,
    response: Response,
    if_match: IfMatch = None,
) -> ServiceOut:
    service = await service_rules.update(session, service_id, body, if_match)
    return _out(response, service)


@router.delete(
    "/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=problem_responses(404, 409, 412, 428),
)
async def delete_service(service_id: uuid.UUID, session: Session, if_match: IfMatch = None) -> None:
    await service_rules.delete(session, service_id, if_match)
