"""POST /api/v1/events/deployments (§7.6): auth, idempotency, out-of-order events."""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import assert_problem, create_service, error_fields

URL = "/api/v1/events/deployments"
KEY = {"X-API-Key": os.environ["INGEST_API_KEY"]}
T0 = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def event(**fields: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "service_slug": "checkout-api",
        "external_id": "gha-123456789-1-production",
        "environment": "production",
        "release": "v1.4.2",
        "head_sha": "9f2c1ab",
        "status": "in_progress",
        "started_at": iso(T0),
        "deployed_by": "github-actions",
        "pipeline_url": "https://github.com/org/repo/actions/runs/123456789",
    }
    payload.update(fields)
    return payload


FINISHED = {"status": "succeeded", "finished_at": iso(T0 + timedelta(minutes=7, seconds=30))}
COMMITS = [{"sha": "9f2c1ab", "committed_at": iso(T0 - timedelta(hours=14))}]


@pytest.fixture
async def service(api: AsyncClient) -> dict[str, Any]:
    return await create_service(api, "checkout-api")


async def deployment_count(engine: AsyncEngine) -> int:
    async with engine.connect() as conn:
        return int(await conn.scalar(text("SELECT count(*) FROM dora.deployments")) or 0)


# ---- auth ----


@pytest.mark.parametrize(
    "headers",
    [{}, {"X-API-Key": ""}, {"X-API-Key": "wrong-key-" + "x" * 30}, {"x-api-key": "short"}],
)
async def test_missing_or_bad_key_is_401(
    api: AsyncClient, service: dict[str, Any], headers: dict[str, str]
) -> None:
    resp = await api.post(URL, json=event(), headers=headers)
    assert_problem(resp, 401, slug="unauthorized")
    assert resp.headers["www-authenticate"].startswith("ApiKey")


async def test_auth_is_checked_before_the_body(api: AsyncClient) -> None:
    # An unauthenticated caller learns nothing about validation rules.
    assert_problem(await api.post(URL, json={"nonsense": True}), 401)


async def test_crud_endpoints_do_not_require_the_key(api: AsyncClient) -> None:
    assert (await api.get("/api/v1/services")).status_code == 200


# ---- create / idempotency ----


async def test_unknown_service_slug_is_422_and_not_created(
    api: AsyncClient, owner_engine: AsyncEngine
) -> None:
    body = assert_problem(
        await api.post(URL, json=event(service_slug="typo-svc"), headers=KEY), 422
    )
    assert error_fields(body) == {"service_slug"}
    services = (await api.get("/api/v1/services")).json()
    assert services["total"] == 0


async def test_external_id_is_required(api: AsyncClient, service: dict[str, Any]) -> None:
    payload = event()
    del payload["external_id"]
    body = assert_problem(await api.post(URL, json=payload, headers=KEY), 422)
    assert error_fields(body) == {"external_id"}


async def test_start_then_finish_is_one_deployment(
    api: AsyncClient, service: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    """E2E scenario 2: in_progress then succeeded for the same external_id."""
    started = await api.post(URL, json=event(), headers=KEY)
    assert started.status_code == 201, started.text
    body = started.json()
    assert started.headers["location"] == f"/api/v1/deployments/{body['id']}"
    assert started.headers["etag"] == '"1"'
    assert (body["status"], body["service_id"], body["ignored"]) == (
        "in_progress",
        service["id"],
        None,
    )

    finished = await api.post(URL, json=event(**FINISHED, commits=COMMITS), headers=KEY)
    assert finished.status_code == 200, finished.text
    done = finished.json()
    assert done["id"] == body["id"]
    assert (done["status"], done["version"]) == ("succeeded", 2)
    assert finished.headers["etag"] == '"2"'
    assert [c["sha"] for c in done["commits"]] == ["9f2c1ab"]
    assert await deployment_count(owner_engine) == 1


async def test_identical_replay_changes_nothing(
    api: AsyncClient, service: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    """E2E scenario 3."""
    payload = event(**FINISHED, commits=COMMITS)
    first = await api.post(URL, json=payload, headers=KEY)
    assert first.status_code == 201
    replay = await api.post(URL, json=payload, headers=KEY)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert replay.headers["etag"] == '"1"'
    assert await deployment_count(owner_engine) == 1


# ---- out-of-order and conflicts ----


async def test_late_in_progress_is_ignored_as_stale(
    api: AsyncClient, service: dict[str, Any]
) -> None:
    """E2E scenario 4: succeeded arrives first, then a late in_progress."""
    finished = await api.post(URL, json=event(**FINISHED), headers=KEY)
    assert finished.status_code == 201

    late = await api.post(
        URL, json=event(release="v0-should-be-ignored", deployed_by="someone-else"), headers=KEY
    )
    assert late.status_code == 200
    body = late.json()
    assert body["ignored"] == "stale_event"
    assert body["status"] == "succeeded"
    # A stale event changes nothing at all, not even its other fields.
    assert (body["release"], body["deployed_by"], body["version"]) == (
        "v1.4.2",
        "github-actions",
        1,
    )


async def test_late_succeeded_after_rollback_is_stale(
    api: AsyncClient, service: dict[str, Any]
) -> None:
    await api.post(URL, json=event(**FINISHED), headers=KEY)
    rolled = await api.post(
        URL, json=event(status="rolled_back", finished_at=FINISHED["finished_at"]), headers=KEY
    )
    assert rolled.json()["status"] == "rolled_back"
    late = await api.post(URL, json=event(**FINISHED), headers=KEY)
    assert late.status_code == 200
    assert late.json()["ignored"] == "stale_event"
    assert late.json()["status"] == "rolled_back"


async def test_genuine_contradiction_is_409(api: AsyncClient, service: dict[str, Any]) -> None:
    await api.post(URL, json=event(**FINISHED), headers=KEY)
    resp = await api.post(
        URL, json=event(status="failed", finished_at=FINISHED["finished_at"]), headers=KEY
    )
    assert_problem(resp, 409, slug="conflict")


async def test_environment_is_immutable_per_external_id(
    api: AsyncClient, service: dict[str, Any]
) -> None:
    await api.post(URL, json=event(), headers=KEY)
    resp = await api.post(URL, json=event(environment="staging"), headers=KEY)
    assert error_fields(assert_problem(resp, 422)) == {"environment"}


async def test_omitted_fields_are_kept_on_update(api: AsyncClient, service: dict[str, Any]) -> None:
    await api.post(URL, json=event(kind="remediation"), headers=KEY)
    finish = event(**FINISHED)
    del finish["deployed_by"]  # omitted, not cleared
    resp = await api.post(URL, json=finish, headers=KEY)
    body = resp.json()
    assert body["kind"] == "remediation"  # default "planned" didn't overwrite it
    assert body["deployed_by"] == "github-actions"


async def test_same_external_id_on_another_service_is_separate(
    api: AsyncClient, service: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    await create_service(api, "catalog-svc")
    assert (await api.post(URL, json=event(), headers=KEY)).status_code == 201
    other = await api.post(URL, json=event(service_slug="catalog-svc"), headers=KEY)
    assert other.status_code == 201
    assert await deployment_count(owner_engine) == 2


async def test_concurrent_first_deliveries_create_one_deployment(
    api: AsyncClient, service: dict[str, Any], owner_engine: AsyncEngine
) -> None:
    """A retried webhook can arrive twice at once; exactly one row may result."""
    payload = event(**FINISHED, commits=COMMITS)
    results = await asyncio.gather(*(api.post(URL, json=payload, headers=KEY) for _ in range(5)))
    statuses = sorted(r.status_code for r in results)
    assert statuses == [200, 200, 200, 200, 201], [r.text for r in results]
    assert len({r.json()["id"] for r in results}) == 1
    assert await deployment_count(owner_engine) == 1
