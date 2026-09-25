"""Small helpers for integration tests."""

import uuid
from datetime import datetime
from typing import Any

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

PROBLEM_JSON = "application/problem+json"


def assert_problem(resp: Response, status: int, *, slug: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"] == PROBLEM_JSON
    body: dict[str, Any] = resp.json()
    assert body["status"] == status
    assert body["title"]
    assert body["instance"] == resp.request.url.path
    if slug is not None:
        assert body["type"] == f"urn:dora:problem:{slug}"
    return body


def error_fields(body: dict[str, Any]) -> set[str]:
    return {e["field"] for e in body.get("errors", [])}


async def create_service(
    api: AsyncClient, slug: str = "checkout-api", **fields: Any
) -> dict[str, Any]:
    payload = {"slug": slug, "name": slug.replace("-", " ").title(), "owner_team": "payments"}
    payload.update(fields)
    resp = await api.post("/api/v1/services", json=payload)
    assert resp.status_code == 201, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def insert_deployment(
    engine: AsyncEngine,
    service_id: str | uuid.UUID,
    *,
    status: str = "succeeded",
    environment: str = "production",
    kind: str = "planned",
    started_at: datetime,
    finished_at: datetime | None,
    release: str = "v1.0.0",
) -> str:
    """Arrange a deployment row directly (as dora_app) until the deployments API exists."""
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO dora.deployments "
                "(service_id, environment, kind, release, status, started_at, finished_at) "
                "VALUES (:service_id, :environment, :kind, :release, :status, :started_at, "
                ":finished_at) RETURNING id"
            ),
            {
                "service_id": str(service_id),
                "environment": environment,
                "kind": kind,
                "release": release,
                "status": status,
                "started_at": started_at,
                "finished_at": finished_at,
            },
        )
        return str(row.scalar_one())


async def insert_commit(
    engine: AsyncEngine, service_id: str, sha: str, committed_at: datetime
) -> str:
    async with engine.begin() as conn:
        row = await conn.execute(
            text(
                "INSERT INTO dora.commits (service_id, sha, committed_at) "
                "VALUES (:service_id, :sha, :committed_at) RETURNING id"
            ),
            {"service_id": service_id, "sha": sha, "committed_at": committed_at},
        )
        return str(row.scalar_one())
