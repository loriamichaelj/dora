"""/api/v1/failures (§7.5) and the §6.3 failure rules."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import (
    assert_problem,
    create_service,
    error_fields,
    insert_deployment,
)

FINISHED = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
STARTED = FINISHED - timedelta(minutes=10)


def iso(dt: datetime) -> str:
    return dt.isoformat()


@pytest.fixture
async def live_deployment(api: AsyncClient, app_engine: AsyncEngine) -> dict[str, str]:
    service_id = (await create_service(api))["id"]
    deployment_id = await insert_deployment(
        app_engine, service_id, started_at=STARTED, finished_at=FINISHED
    )
    return {"service_id": service_id, "deployment_id": deployment_id}


async def post_failure(api: AsyncClient, deployment_id: str, **fields: Any) -> Any:
    payload: dict[str, Any] = {
        "deployment_id": deployment_id,
        "severity": "sev2",
        "summary": "Checkout errors spiked",
        "detected_at": iso(FINISHED + timedelta(hours=1)),
    }
    payload.update(fields)
    return await api.post("/api/v1/failures", json=payload)


async def test_create_failure(api: AsyncClient, live_deployment: dict[str, str]) -> None:
    resp = await post_failure(
        api,
        live_deployment["deployment_id"],
        detected_at="2026-09-20T13:00:00+02:00",  # any offset is accepted...
        external_ref="INC-42",
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert resp.headers["location"] == f"/api/v1/failures/{body['id']}"
    assert resp.headers["etag"] == '"1"'
    assert body["detected_at"] == "2026-09-20T11:00:00Z"  # ...and returned as UTC
    assert body["service_id"] == live_deployment["service_id"]
    assert body["resolved_at"] is None
    assert body["external_ref"] == "INC-42"

    got = await api.get(f"/api/v1/failures/{body['id']}")
    assert got.status_code == 200
    assert got.json() == body


@pytest.mark.parametrize("status", ["succeeded", "rolled_back"])
async def test_both_live_statuses_accept_failures(
    api: AsyncClient, app_engine: AsyncEngine, status: str
) -> None:
    service_id = (await create_service(api))["id"]
    dep = await insert_deployment(
        app_engine, service_id, status=status, started_at=STARTED, finished_at=FINISHED
    )
    assert (await post_failure(api, dep)).status_code == 201


@pytest.mark.parametrize(("status", "finished_at"), [("failed", FINISHED), ("in_progress", None)])
async def test_failure_requires_live_deployment(
    api: AsyncClient, app_engine: AsyncEngine, status: str, finished_at: datetime | None
) -> None:
    service_id = (await create_service(api))["id"]
    dep = await insert_deployment(
        app_engine, service_id, status=status, started_at=STARTED, finished_at=finished_at
    )
    assert_problem(await post_failure(api, dep), 409, slug="conflict")


async def test_unknown_deployment_is_422(api: AsyncClient) -> None:
    body = assert_problem(await post_failure(api, str(uuid.uuid4())), 422)
    assert error_fields(body) == {"deployment_id"}


async def test_timestamp_rules(api: AsyncClient, live_deployment: dict[str, str]) -> None:
    dep = live_deployment["deployment_id"]
    before_finish = assert_problem(
        await post_failure(api, dep, detected_at=iso(FINISHED - timedelta(seconds=1))), 422
    )
    assert error_fields(before_finish) == {"detected_at"}

    resolved_early = assert_problem(
        await post_failure(
            api,
            dep,
            detected_at=iso(FINISHED + timedelta(hours=2)),
            resolved_at=iso(FINISHED + timedelta(hours=1)),
        ),
        422,
    )
    assert error_fields(resolved_early) == {"resolved_at"}

    naive = assert_problem(await post_failure(api, dep, detected_at="2026-09-20T12:00:00"), 422)
    assert error_fields(naive) == {"detected_at"}

    # detected exactly at finish is allowed
    assert (await post_failure(api, dep, detected_at=iso(FINISHED))).status_code == 201


async def test_resolve_then_reopen(api: AsyncClient, live_deployment: dict[str, str]) -> None:
    created = (await post_failure(api, live_deployment["deployment_id"])).json()
    url = f"/api/v1/failures/{created['id']}"
    resolved_at = FINISHED + timedelta(hours=3)

    resp = await api.patch(url, json={"resolved_at": iso(resolved_at)}, headers={"If-Match": '"1"'})
    assert resp.status_code == 200, resp.text
    assert resp.headers["etag"] == '"2"'
    assert resp.json()["resolved_at"] == "2026-09-20T13:00:00Z"

    too_early = await api.patch(
        url, json={"resolved_at": iso(FINISHED)}, headers={"If-Match": '"2"'}
    )
    assert error_fields(assert_problem(too_early, 422)) == {"resolved_at"}

    assert_problem(await api.patch(url, json={"severity": None}, headers={"If-Match": '"2"'}), 422)

    reopened = await api.patch(url, json={"resolved_at": None}, headers={"If-Match": '"2"'})
    assert reopened.status_code == 200
    assert reopened.json()["resolved_at"] is None
    assert reopened.json()["version"] == 3


async def test_move_failure_to_another_deployment_is_revalidated(
    api: AsyncClient, app_engine: AsyncEngine, live_deployment: dict[str, str]
) -> None:
    created = (await post_failure(api, live_deployment["deployment_id"])).json()
    url = f"/api/v1/failures/{created['id']}"
    failed = await insert_deployment(
        app_engine,
        live_deployment["service_id"],
        status="failed",
        started_at=STARTED,
        finished_at=FINISHED,
    )
    assert_problem(
        await api.patch(url, json={"deployment_id": failed}, headers={"If-Match": '"1"'}), 409
    )


async def test_list_filters(api: AsyncClient, app_engine: AsyncEngine) -> None:
    svc_a = (await create_service(api, "svc-a"))["id"]
    svc_b = (await create_service(api, "svc-b"))["id"]
    dep_a = await insert_deployment(app_engine, svc_a, started_at=STARTED, finished_at=FINISHED)
    dep_b = await insert_deployment(app_engine, svc_b, started_at=STARTED, finished_at=FINISHED)
    hour = timedelta(hours=1)
    f1 = (await post_failure(api, dep_a, severity="sev1", detected_at=iso(FINISHED + hour))).json()
    f2 = (
        await post_failure(
            api,
            dep_a,
            detected_at=iso(FINISHED + 2 * hour),
            resolved_at=iso(FINISHED + 3 * hour),
        )
    ).json()
    f3 = (await post_failure(api, dep_b, detected_at=iso(FINISHED + 4 * hour))).json()

    async def ids(**params: object) -> list[str]:
        resp = await api.get("/api/v1/failures", params=params)
        assert resp.status_code == 200, resp.text
        return [f["id"] for f in resp.json()["items"]]

    assert await ids() == [f3["id"], f2["id"], f1["id"]]  # default -detected_at
    assert await ids(sort="detected_at") == [f1["id"], f2["id"], f3["id"]]
    assert await ids(service_id=svc_a) == [f2["id"], f1["id"]]
    assert await ids(deployment_id=dep_b) == [f3["id"]]
    assert await ids(severity="sev1") == [f1["id"]]
    assert await ids(open="true") == [f3["id"], f1["id"]]
    assert await ids(open="false") == [f2["id"]]
    assert_problem(await api.get("/api/v1/failures", params={"severity": "sev9"}), 422)


async def test_delete_failure(api: AsyncClient, live_deployment: dict[str, str]) -> None:
    created = (await post_failure(api, live_deployment["deployment_id"])).json()
    url = f"/api/v1/failures/{created['id']}"
    assert_problem(await api.delete(url), 428)
    assert (await api.delete(url, headers={"If-Match": '"1"'})).status_code == 204
    assert_problem(await api.get(url), 404)
