"""/api/v1/services (§7.3) plus the cross-cutting §7.1 conventions."""

import asyncio
import re
import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.integration.helpers import (
    assert_problem,
    create_service,
    error_fields,
    insert_commit,
    insert_deployment,
)

UTC_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
T0 = datetime(2026, 9, 20, 10, 0, tzinfo=UTC)


# ---- create ----


async def test_create_returns_201_location_and_strong_etag(api: AsyncClient) -> None:
    resp = await api.post(
        "/api/v1/services",
        json={
            "slug": "checkout-api",
            "name": "Checkout API",
            "owner_team": "payments",
            "repo_url": "https://github.com/org/checkout",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert resp.headers["location"] == f"/api/v1/services/{body['id']}"
    assert resp.headers["etag"] == '"1"'
    assert body["version"] == 1
    assert uuid.UUID(body["id"]).version == 7
    assert UTC_Z.match(body["created_at"])
    assert UTC_Z.match(body["updated_at"])
    assert {k: body[k] for k in ("slug", "name", "owner_team", "repo_url")} == {
        "slug": "checkout-api",
        "name": "Checkout API",
        "owner_team": "payments",
        "repo_url": "https://github.com/org/checkout",
    }


async def test_duplicate_slug_is_409(api: AsyncClient) -> None:
    await create_service(api, "checkout-api")
    resp = await api.post(
        "/api/v1/services", json={"slug": "checkout-api", "name": "Dup", "owner_team": "x"}
    )
    body = assert_problem(resp, 409, slug="conflict")
    assert error_fields(body) == {"slug"}


@pytest.mark.parametrize(
    ("payload", "fields"),
    [
        ({"slug": "Bad Slug", "name": "n", "owner_team": "t"}, {"slug"}),
        ({"slug": "a", "name": "n", "owner_team": "t"}, {"slug"}),  # needs 2+ chars
        ({"slug": "ok-slug", "name": "  ", "owner_team": "t"}, {"name"}),
        ({"slug": "ok-slug", "name": "n" * 201, "owner_team": "t"}, {"name"}),
        ({"slug": "ok-slug", "name": "n"}, {"owner_team"}),
        ({"slug": "ok-slug", "name": "n", "owner_team": "t", "surprise": 1}, {"surprise"}),
    ],
)
async def test_create_validation_errors_are_field_level(
    api: AsyncClient, payload: dict[str, object], fields: set[str]
) -> None:
    body = assert_problem(await api.post("/api/v1/services", json=payload), 422, slug="validation")
    assert error_fields(body) == fields
    assert all(e["location"] == "body" for e in body["errors"])


# ---- read ----


async def test_get_returns_etag_and_404s_are_problems(api: AsyncClient) -> None:
    created = await create_service(api)
    resp = await api.get(f"/api/v1/services/{created['id']}")
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"1"'
    assert resp.json() == created

    assert_problem(await api.get(f"/api/v1/services/{uuid.uuid4()}"), 404, slug="not-found")
    body = assert_problem(await api.get("/api/v1/services/not-a-uuid"), 422)
    assert body["errors"][0]["location"] == "path"
    assert_problem(await api.get("/api/v1/no-such-route"), 404)


# ---- list: filters, sort, pagination ----


async def test_list_pagination_envelope(api: AsyncClient) -> None:
    for i in range(5):
        await create_service(api, f"svc-{i}", name=f"Service {i}")
    resp = await api.get("/api/v1/services", params={"limit": 2, "offset": 1})
    assert resp.status_code == 200
    page = resp.json()
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)
    assert [s["slug"] for s in page["items"]] == ["svc-1", "svc-2"]

    default = (await api.get("/api/v1/services")).json()
    assert default["limit"] == 50
    assert default["offset"] == 0


@pytest.mark.parametrize(
    "params", [{"limit": 201}, {"limit": 0}, {"offset": -1}, {"sort": "slug"}, {"sort": "--name"}]
)
async def test_list_rejects_bad_paging_and_sort(
    api: AsyncClient, params: dict[str, object]
) -> None:
    body = assert_problem(await api.get("/api/v1/services", params=params), 422)
    assert body["errors"][0]["location"] == "query"


async def test_list_sort_and_filters(api: AsyncClient) -> None:
    await create_service(api, "bravo", name="Bravo", owner_team="core")
    await create_service(api, "alpha", name="Alpha", owner_team="payments")
    await create_service(api, "charlie-100", name="Charlie 100%", owner_team="core")

    async def slugs(**params: object) -> list[str]:
        resp = await api.get("/api/v1/services", params=params)
        assert resp.status_code == 200, resp.text
        return [s["slug"] for s in resp.json()["items"]]

    assert await slugs() == ["alpha", "bravo", "charlie-100"]
    assert await slugs(sort="-name") == ["charlie-100", "bravo", "alpha"]
    assert await slugs(sort="created_at") == ["bravo", "alpha", "charlie-100"]
    assert await slugs(owner_team="core") == ["bravo", "charlie-100"]
    assert await slugs(q="ALP") == ["alpha"]
    assert await slugs(q="100%") == ["charlie-100"]  # wildcard characters match literally
    assert await slugs(q="%") == ["charlie-100"]


# ---- update: optimistic concurrency and immutability ----


async def test_patch_requires_if_match(api: AsyncClient) -> None:
    sid = (await create_service(api))["id"]
    url = f"/api/v1/services/{sid}"
    assert_problem(await api.patch(url, json={"name": "X"}), 428, slug="precondition-required")
    assert_problem(
        await api.patch(url, json={"name": "X"}, headers={"If-Match": '"7"'}),
        412,
        slug="precondition-failed",
    )
    # Weak validators never satisfy If-Match (strong comparison, RFC 9110).
    assert_problem(await api.patch(url, json={"name": "X"}, headers={"If-Match": 'W/"1"'}), 412)


async def test_etag_round_trip_bumps_version(api: AsyncClient) -> None:
    sid = (await create_service(api))["id"]
    url = f"/api/v1/services/{sid}"
    got = await api.get(url)

    resp = await api.patch(url, json={"name": "Renamed"}, headers={"If-Match": got.headers["etag"]})
    assert resp.status_code == 200
    assert resp.headers["etag"] == '"2"'
    body = resp.json()
    assert (body["name"], body["version"]) == ("Renamed", 2)
    assert body["updated_at"] > got.json()["updated_at"]

    # The old ETag is now stale.
    assert_problem(
        await api.patch(url, json={"name": "Again"}, headers={"If-Match": got.headers["etag"]}), 412
    )


async def test_noop_patch_does_not_bump_version(api: AsyncClient) -> None:
    created = await create_service(api, "checkout-api", name="Checkout Api")
    url = f"/api/v1/services/{created['id']}"
    resp = await api.patch(
        url, json={"name": "Checkout Api", "slug": "checkout-api"}, headers={"If-Match": '"1"'}
    )
    assert resp.status_code == 200
    assert resp.json() == created
    assert resp.headers["etag"] == '"1"'


async def test_slug_is_immutable_and_required_fields_reject_null(api: AsyncClient) -> None:
    sid = (await create_service(api, repo_url="https://example.com/r"))["id"]
    url = f"/api/v1/services/{sid}"
    body = assert_problem(
        await api.patch(url, json={"slug": "new-slug"}, headers={"If-Match": '"1"'}), 422
    )
    assert error_fields(body) == {"slug"}
    assert_problem(await api.patch(url, json={"name": None}, headers={"If-Match": '"1"'}), 422)

    cleared = await api.patch(url, json={"repo_url": None}, headers={"If-Match": '"1"'})
    assert cleared.status_code == 200
    assert cleared.json()["repo_url"] is None


async def test_if_match_star_and_lists(api: AsyncClient) -> None:
    sid = (await create_service(api))["id"]
    url = f"/api/v1/services/{sid}"
    ok = await api.patch(url, json={"name": "A"}, headers={"If-Match": "*"})
    assert ok.status_code == 200
    ok = await api.patch(url, json={"name": "B"}, headers={"If-Match": '"9", "2"'})
    assert ok.status_code == 200


async def test_concurrent_writers_one_wins(api: AsyncClient) -> None:
    sid = (await create_service(api))["id"]
    url = f"/api/v1/services/{sid}"
    results = await asyncio.gather(
        api.patch(url, json={"name": "Writer A"}, headers={"If-Match": '"1"'}),
        api.patch(url, json={"name": "Writer B"}, headers={"If-Match": '"1"'}),
    )
    assert sorted(r.status_code for r in results) == [200, 412]


# ---- delete ----


async def test_delete_flow(api: AsyncClient) -> None:
    sid = (await create_service(api))["id"]
    url = f"/api/v1/services/{sid}"
    assert_problem(await api.delete(url), 428)
    assert_problem(await api.delete(url, headers={"If-Match": '"2"'}), 412)
    resp = await api.delete(url, headers={"If-Match": '"1"'})
    assert resp.status_code == 204
    assert resp.content == b""
    assert_problem(await api.get(url), 404)
    assert_problem(await api.delete(url, headers={"If-Match": '"1"'}), 404)


async def test_delete_with_deployments_or_commits_is_409(
    api: AsyncClient, app_engine: AsyncEngine
) -> None:
    with_deploy = (await create_service(api, "with-deploy"))["id"]
    await insert_deployment(app_engine, with_deploy, started_at=T0, finished_at=T0)
    with_commit = (await create_service(api, "with-commit"))["id"]
    await insert_commit(app_engine, with_commit, "abc1234", T0)

    for sid in (with_deploy, with_commit):
        resp = await api.delete(f"/api/v1/services/{sid}", headers={"If-Match": '"1"'})
        assert_problem(resp, 409, slug="conflict")
