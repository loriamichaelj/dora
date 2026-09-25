"""Operational endpoints served at the root, outside /api/v1 (§7.2)."""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(tags=["operational"])
log = structlog.get_logger(__name__)

READINESS_TIMEOUT_SECONDS = 2.0


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: dict[str, Literal["ok", "timeout", "error"]]


class VersionResponse(BaseModel):
    version: str
    git_sha: str
    build_time: str


@router.get("/healthz", response_model=LivenessResponse)
async def healthz() -> LivenessResponse:
    """Liveness only: never touches the database (D1)."""
    return LivenessResponse(status="ok")


async def _check_database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


def _retrieve_result(task: "asyncio.Task[None]") -> None:
    # A probe that outlived its request still finishes; collect its outcome so
    # asyncio never reports an unretrieved exception.
    if not task.cancelled():
        task.exception()


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "A dependency is unavailable"}},
)
async def readyz(request: Request) -> JSONResponse:
    """Readiness: `SELECT 1` within 2 seconds. For traffic routing, never for
    container health, so a database blip can't get every API container killed.

    The probe runs as its own task and is waited on, never cancelled: cancelling
    a query against a frozen server leaves connection cleanup blocked on that
    server, which would hang this endpoint for as long as the outage lasts. At
    most one probe is in flight, so repeated checks during an outage can't pile
    up connections (D49)."""
    state = request.app.state
    probe: asyncio.Task[None] | None = getattr(state, "readiness_probe", None)
    if probe is None or probe.done():
        probe = asyncio.create_task(_check_database(state.engine))
        probe.add_done_callback(_retrieve_result)
        state.readiness_probe = probe

    done, _ = await asyncio.wait({probe}, timeout=READINESS_TIMEOUT_SECONDS)
    database: Literal["ok", "timeout", "error"]
    if not done:
        database = "timeout"
    elif (exc := probe.exception()) is not None:
        log.warning("readiness_check_failed", check="database", error=type(exc).__name__)
        database = "error"
    else:
        database = "ok"
    if database != "ok":
        log.warning("not_ready", check="database", result=database)

    ready = database == "ok"
    body = ReadinessResponse(
        status="ready" if ready else "not_ready", checks={"database": database}
    )
    return JSONResponse(body.model_dump(), status_code=200 if ready else 503)


@router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> Response:
    """Prometheus exposition. Served by the API only; nginx never proxies it."""
    return Response(
        generate_latest(request.app.state.metrics.registry), media_type=CONTENT_TYPE_LATEST
    )


@router.get("/version", response_model=VersionResponse)
async def version(request: Request) -> VersionResponse:
    settings = request.app.state.settings
    return VersionResponse(
        version=settings.app_version,
        git_sha=settings.git_sha,
        build_time=settings.build_time,
    )
