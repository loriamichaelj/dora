"""POST /api/v1/events/deployments: machine-facing ingest (§7.6)."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import APIKeyHeader

from app.concurrency import etag
from app.deps import Session
from app.problems import Unauthorized, problem_responses
from app.routers.deployments import to_detail
from app.schemas.ingest import DeploymentEvent, IngestResult
from app.services import ingest as ingest_rules

# auto_error=False: we raise our own problem+json 401 instead of FastAPI's 403.
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="IngestApiKey")


async def require_ingest_key(
    request: Request, api_key: Annotated[str | None, Depends(api_key_header)]
) -> None:
    expected = request.app.state.settings.ingest_api_key.get_secret_value().encode()
    # Constant-time comparison; never log the presented key.
    if api_key is None or not hmac.compare_digest(api_key.encode(), expected):
        raise Unauthorized("A valid X-API-Key header is required.")


router = APIRouter(prefix="/events", tags=["ingest"], dependencies=[Depends(require_ingest_key)])


@router.post(
    "/deployments",
    response_model=IngestResult,
    status_code=status.HTTP_200_OK,
    responses={
        201: {"model": IngestResult, "description": "Deployment created"},
        **problem_responses(401, 409),
    },
)
async def ingest_deployment_event(
    event: DeploymentEvent, session: Session, response: Response
) -> IngestResult:
    outcome = await ingest_rules.ingest(session, event)
    detail = to_detail(outcome.view)
    if outcome.created:
        response.status_code = status.HTTP_201_CREATED
        response.headers["Location"] = f"/api/v1/deployments/{detail.id}"
    response.headers["ETag"] = etag(detail.version)
    return IngestResult(**detail.model_dump(), ignored="stale_event" if outcome.stale else None)
