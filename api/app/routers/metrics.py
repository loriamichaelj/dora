"""/api/v1/metrics/dora (§7.8)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.deps import Session
from app.dora.queries import Bucket
from app.problems import problem_responses
from app.schemas.deployments import Environment
from app.schemas.metrics import DoraSummary, DoraTimeseries
from app.services import metrics as metric_rules

router = APIRouter(prefix="/metrics/dora", tags=["metrics"])

ServiceFilter = Annotated[uuid.UUID | None, Query(description="Omit for org-wide metrics")]
EnvironmentFilter = Annotated[Environment, Query()]
From = Annotated[
    AwareDatetime | None,
    Query(alias="from", description="Window start (inclusive). Default: `to` minus 30 days"),
]
To = Annotated[AwareDatetime | None, Query(description="Window end (exclusive). Default: now")]


@router.get("", response_model=DoraSummary, responses=problem_responses())
async def dora_summary(
    session: Session,
    service_id: ServiceFilter = None,
    environment: EnvironmentFilter = "production",
    from_: From = None,
    to: To = None,
) -> DoraSummary:
    query = await metric_rules.build_query(
        session, environment=environment, from_ts=from_, to_ts=to, service_id=service_id
    )
    return await metric_rules.summary(session, query)


@router.get("/timeseries", response_model=DoraTimeseries, responses=problem_responses())
async def dora_timeseries(
    session: Session,
    service_id: ServiceFilter = None,
    environment: EnvironmentFilter = "production",
    from_: From = None,
    to: To = None,
    bucket: Annotated[Bucket, Query()] = "week",
) -> DoraTimeseries:
    query = await metric_rules.build_query(
        session, environment=environment, from_ts=from_, to_ts=to, service_id=service_id
    )
    return await metric_rules.timeseries(session, query, bucket)
