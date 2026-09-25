"""/api/v1/deployments (§7.4): CRUD, commit upsert, transitions, immutability."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from structlog.testing import capture_logs

from app.repositories import commits as commits_repo
from tests.integration.helpers import assert_problem, create_service, error_fields

T0 = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)
URL = "/api/v1/deployments"


def iso(dt: datetime) -> str:
    return dt.isoformat()


def commit(sha: str, hours_before: float = 12, **extra: Any) -> dict[str, Any]:
    return {"sha": sha, "committed_at": iso(T0 - timedelta(hours=hours_before)), **extra}


async def post_deployment(api: AsyncClient, service_id: str, **fields: Any) -> Any:
    payload: dict[str, Any] = {
        "service_id": service_id,
        "environment": "production",
        "release": "v1.4.2",
        "status": "succeeded",
        "started_at": iso(T0),
        "finished_at": iso(T0 + timedelta(minutes=7, seconds=30)),
    }
    payload.update(fields)
    return await api.post(URL, json=payload)


@pytest.fixture
async def service_id(api: AsyncClient) -> str:
    return str((await create_service(api))["id"])


# ---- create ----


async def test_create_with_commits(api: AsyncClient, service_id: str) -> None:
    resp = await post_deployment(
        api,
        service_id,
        head_sha="9F2C1AB",  # upper case is normalized
        deployed_by="github-actions",
        pipeline_url="https://github.com/org/repo/actions/runs/123",
        commits=[
            commit("9f2c1ab", 14, author="dev@example.com", message="fix: retry on 503"),
            commit("1234567", 20),
        ],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert resp.headers["location"] == f"{URL}/{body['id']}"
    assert resp.headers["etag"] == '"1"'
    assert body["kind"] == "planned"  # default
    assert body["head_sha"] == "9f2c1ab"
    assert body["finished_at"] == "2026-09-20T10:07:30Z"
    assert [c["sha"] for c in body["commits"]] == ["9f2c1ab", "1234567"]  # newest first
    assert body["commits"][0]["author"] == "dev@example.com"
    assert body["failures"] == []

    got = await api.get(f"{URL}/{body['id']}")
    assert got.status_code == 200
    assert got.json() == body


@pytest.mark.parametrize(
    ("fields", "bad"),
    [
        ({"status": "succeeded", "finished_at": None}, {"finished_at"}),
        ({"status": "in_progress"}, {"finished_at"}),  # finished_at present
        ({"finished_at": iso(T0 - timedelta(seconds=1))}, {"finished_at"}),
        ({"environment": "prod"}, {"environment"}),
        ({"status": "done"}, {"status"}),
        ({"kind": "hotfix"}, {"kind"}),
        ({"head_sha": "xyz"}, {"head_sha"}),
        ({"release": ""}, {"release"}),
        ({"started_at": "2026-09-20T10:00:00"}, {"started_at"}),  # naive
        ({"commits": [{"sha": "nothex!", "committed_at": iso(T0)}]}, {"commits.0.sha"}),
    ],
)
async def test_create_validation(
    api: AsyncClient, service_id: str, fields: dict[str, Any], bad: set[str]
) -> None:
    body = assert_problem(await post_deployment(api, service_id, **fields), 422)
    assert error_fields(body) == bad


async def test_unknown_service_is_422(api: AsyncClient) -> None:
    body = assert_problem(await post_deployment(api, str(uuid.uuid4())), 422)
    assert error_fields(body) == {"service_id"}


async def test_duplicate_external_id_is_409_per_service(api: AsyncClient, service_id: str) -> None:
    assert (await post_deployment(api, service_id, external_id="run-1")).status_code == 201
    dup = assert_problem(await post_deployment(api, service_id, external_id="run-1"), 409)
    assert error_fields(dup) == {"external_id"}
    other = (await create_service(api, "other-svc"))["id"]
    assert (await post_deployment(api, other, external_id="run-1")).status_code == 201


# ---- commit upsert ----


async def test_commit_upsert_first_write_wins(
    api: AsyncClient, service_id: str, owner_engine: AsyncEngine
) -> None:
    first = await post_deployment(api, service_id, commits=[commit("aaaaaaa", 10, author="a")])
    with capture_logs() as logs:
        second = await post_deployment(
            api,
            service_id,
            started_at=iso(T0 + timedelta(days=1)),
            finished_at=iso(T0 + timedelta(days=1, minutes=5)),
            commits=[commit("aaaaaaa", 30, author="b"), commit("bbbbbbb", 5)],
        )
    assert second.status_code == 201, second.text
    [warning] = [e for e in logs if e["event"] == "commit_committed_at_conflict"]
    assert warning["log_level"] == "warning"
    assert warning["sha"] == "aaaaaaa"
    assert (warning["kept"], warning["ignored"]) == (
        (T0 - timedelta(hours=10)).isoformat(),
        (T0 - timedelta(hours=30)).isoformat(),
    )
    shipped = {c["sha"]: c for c in second.json()["commits"]}
    first_commit = first.json()["commits"][0]
    # Same commit row, original committed_at and author kept.
    assert shipped["aaaaaaa"] == first_commit

    async with owner_engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM dora.commits"))
        links = await conn.scalar(text("SELECT count(*) FROM dora.deployment_commits"))
    assert (count, links) == (2, 3)


async def test_duplicate_shas_in_one_request_are_collapsed(
    api: AsyncClient, service_id: str
) -> None:
    resp = await post_deployment(
        api, service_id, commits=[commit("ccccccc", 3), commit("CCCCCCC", 9)]
    )
    assert resp.status_code == 201, resp.text
    commits = resp.json()["commits"]
    assert len(commits) == 1
    assert commits[0]["committed_at"] == iso(T0 - timedelta(hours=3)).replace("+00:00", "Z")


async def test_commits_are_scoped_per_service(api: AsyncClient, service_id: str) -> None:
    other = (await create_service(api, "other-svc"))["id"]
    a = (await post_deployment(api, service_id, commits=[commit("ddddddd")])).json()
    b = (await post_deployment(api, other, commits=[commit("ddddddd")])).json()
    assert a["commits"][0]["id"] != b["commits"][0]["id"]


# ---- list ----


async def test_list_filters_and_sort(api: AsyncClient, service_id: str) -> None:
    other = (await create_service(api, "other-svc"))["id"]
    day = timedelta(days=1)
    d1 = (await post_deployment(api, service_id, started_at=iso(T0), finished_at=iso(T0))).json()
    d2 = (
        await post_deployment(
            api,
            service_id,
            environment="staging",
            kind="remediation",
            started_at=iso(T0 + day),
            finished_at=iso(T0 + day),
        )
    ).json()
    d3 = (
        await post_deployment(
            api, other, status="in_progress", started_at=iso(T0 + 2 * day), finished_at=None
        )
    ).json()

    async def ids(**params: object) -> list[str]:
        resp = await api.get(URL, params=params)
        assert resp.status_code == 200, resp.text
        return [d["id"] for d in resp.json()["items"]]

    assert await ids() == [d3["id"], d2["id"], d1["id"]]
    assert await ids(sort="started_at") == [d1["id"], d2["id"], d3["id"]]
    # finished_at sorts put unfinished deployments last in both directions.
    assert await ids(sort="-finished_at") == [d2["id"], d1["id"], d3["id"]]
    assert await ids(service_id=service_id) == [d2["id"], d1["id"]]
    assert await ids(environment="staging") == [d2["id"]]
    assert await ids(status="in_progress") == [d3["id"]]
    assert await ids(kind="remediation") == [d2["id"]]
    assert await ids(**{"from": iso(T0 + day), "to": iso(T0 + 2 * day)}) == [d2["id"]]
    assert_problem(await api.get(URL, params={"from": "2026-09-20T10:00:00"}), 422)
    assert_problem(await api.get(URL, params={"sort": "release"}), 422)

    item = (await api.get(URL, params={"limit": 1})).json()["items"][0]
    assert "commits" not in item  # list items are summaries


# ---- update: transitions, immutability, concurrency ----


async def test_in_progress_to_succeeded(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id, status="in_progress", finished_at=None)).json()
    url = f"{URL}/{dep['id']}"

    missing_finish = await api.patch(url, json={"status": "succeeded"}, headers={"If-Match": '"1"'})
    assert error_fields(assert_problem(missing_finish, 422)) == {"finished_at"}

    done = await api.patch(
        url,
        json={"status": "succeeded", "finished_at": iso(T0 + timedelta(minutes=9))},
        headers={"If-Match": '"1"'},
    )
    assert done.status_code == 200, done.text
    assert done.headers["etag"] == '"2"'
    assert done.json()["status"] == "succeeded"


@pytest.mark.parametrize(
    ("start", "target"),
    [
        ("succeeded", "in_progress"),
        ("succeeded", "failed"),
        ("failed", "succeeded"),
        ("failed", "rolled_back"),
        ("rolled_back", "succeeded"),
    ],
)
async def test_invalid_transitions_are_409(
    api: AsyncClient, service_id: str, start: str, target: str
) -> None:
    dep = (await post_deployment(api, service_id, status=start)).json()
    body: dict[str, Any] = {"status": target}
    if target == "in_progress":
        body["finished_at"] = None
    resp = await api.patch(f"{URL}/{dep['id']}", json=body, headers={"If-Match": '"1"'})
    problem = assert_problem(resp, 409, slug="conflict")
    assert start in problem["detail"]
    assert target in problem["detail"]


async def test_rollback_keeps_failures_valid(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id)).json()
    url = f"{URL}/{dep['id']}"
    rolled = await api.patch(url, json={"status": "rolled_back"}, headers={"If-Match": '"1"'})
    assert rolled.status_code == 200
    assert rolled.json()["status"] == "rolled_back"
    same = await api.patch(url, json={"status": "rolled_back"}, headers={"If-Match": '"2"'})
    assert same.headers["etag"] == '"2"'  # same -> same is a no-op


async def test_immutable_fields(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id, external_id="run-9")).json()
    url = f"{URL}/{dep['id']}"
    other = (await create_service(api, "other-svc"))["id"]
    resp = await api.patch(
        url,
        json={"service_id": other, "environment": "staging", "external_id": "run-10"},
        headers={"If-Match": '"1"'},
    )
    body = assert_problem(resp, 422)
    assert error_fields(body) == {"service_id", "environment", "external_id"}

    unchanged = await api.patch(
        url,
        json={"service_id": service_id, "environment": "production", "external_id": "run-9"},
        headers={"If-Match": '"1"'},
    )
    assert unchanged.status_code == 200
    assert unchanged.headers["etag"] == '"1"'


async def test_patch_adds_commits_and_bumps_version(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id, commits=[commit("eeeeeee")])).json()
    url = f"{URL}/{dep['id']}"
    resp = await api.patch(
        url,
        json={"commits": [commit("eeeeeee"), commit("fffffff", 2)]},
        headers={"If-Match": '"1"'},
    )
    assert resp.status_code == 200
    assert {c["sha"] for c in resp.json()["commits"]} == {"eeeeeee", "fffffff"}
    assert resp.json()["version"] == 2

    again = await api.patch(
        url, json={"commits": [commit("fffffff", 2)]}, headers={"If-Match": '"2"'}
    )
    assert again.json()["version"] == 2  # nothing new linked


async def test_finished_at_cannot_pass_a_failure(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id)).json()
    detected = T0 + timedelta(hours=1)
    failure = await api.post(
        "/api/v1/failures",
        json={
            "deployment_id": dep["id"],
            "severity": "sev3",
            "summary": "Latency",
            "detected_at": iso(detected),
        },
    )
    assert failure.status_code == 201
    url = f"{URL}/{dep['id']}"
    resp = await api.patch(
        url, json={"finished_at": iso(detected + timedelta(minutes=1))}, headers={"If-Match": '"1"'}
    )
    assert_problem(resp, 409)

    detail = (await api.get(url)).json()
    assert [f["id"] for f in detail["failures"]] == [failure.json()["id"]]
    assert detail["failures"][0]["severity"] == "sev3"


# ---- delete ----


async def test_delete(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id, commits=[commit("abcdef1")])).json()
    url = f"{URL}/{dep['id']}"
    assert_problem(await api.delete(url), 428)
    assert (await api.delete(url, headers={"If-Match": '"1"'})).status_code == 204
    assert_problem(await api.get(url), 404)


async def test_commit_classification_follows_links(
    api: AsyncClient, service_id: str, api_app: FastAPI
) -> None:
    """A commit is a deployment commit while any deployment ships it."""
    shared = [commit("1111111"), commit("2222222")]
    first = (await post_deployment(api, service_id, commits=shared)).json()
    second = (
        await post_deployment(
            api,
            service_id,
            started_at=iso(T0 + timedelta(days=1)),
            finished_at=iso(T0 + timedelta(days=1)),
            commits=[commit("2222222")],
        )
    ).json()

    async def classify() -> tuple[int, int]:
        async with api_app.state.sessionmaker() as session:
            c = await commits_repo.classify_for_service(session, uuid.UUID(service_id))
        return c.deployment_commits, c.non_deployment_commits

    assert await classify() == (2, 0)
    await api.delete(f"{URL}/{first['id']}", headers={"If-Match": '"1"'})
    assert await classify() == (1, 1)  # 2222222 is still shipped by the second deployment

    blocked = await api.delete(f"/api/v1/services/{service_id}", headers={"If-Match": '"1"'})
    assert "1 deployment commit(s)" in assert_problem(blocked, 409)["detail"]

    await api.delete(f"{URL}/{second['id']}", headers={"If-Match": '"1"'})
    assert await classify() == (0, 2)
    resp = await api.delete(f"/api/v1/services/{service_id}", headers={"If-Match": '"1"'})
    assert resp.status_code == 204


async def test_delete_with_failures_is_409(api: AsyncClient, service_id: str) -> None:
    dep = (await post_deployment(api, service_id)).json()
    await api.post(
        "/api/v1/failures",
        json={
            "deployment_id": dep["id"],
            "severity": "sev1",
            "summary": "Down",
            "detected_at": iso(T0 + timedelta(hours=1)),
        },
    )
    resp = await api.delete(f"{URL}/{dep['id']}", headers={"If-Match": '"1"'})
    assert_problem(resp, 409)
