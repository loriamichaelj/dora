"""DORA engine acceptance: golden datasets A, B, C (§12.1-12.3), exactly.

Dataset A is loaded through the public API, so the engine is tested against
data exactly as the application writes it.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import text

from app.dora import queries
from tests.integration.helpers import assert_problem, create_service

SUMMARY = "/api/v1/metrics/dora"
SERIES = "/api/v1/metrics/dora/timeseries"
WINDOW = {"from": "2026-09-01T00:00:00Z", "to": "2026-10-01T00:00:00Z"}


def at(month: int, day: int, hour: int = 10) -> datetime:
    return datetime(2026, month, day, hour, 0, tzinfo=UTC)


async def deploy(
    api: AsyncClient,
    service_id: str,
    finished: datetime,
    commits: list[tuple[str, datetime]],
    *,
    environment: str = "production",
    kind: str = "planned",
    status: str = "succeeded",
) -> str:
    resp = await api.post(
        "/api/v1/deployments",
        json={
            "service_id": service_id,
            "environment": environment,
            "kind": kind,
            "release": f"r-{finished:%m%d}",
            "status": status,
            "started_at": (finished - timedelta(minutes=10)).isoformat(),
            "finished_at": finished.isoformat(),
            "commits": [{"sha": sha, "committed_at": ts.isoformat()} for sha, ts in commits],
        },
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def fail(
    api: AsyncClient, deployment_id: str, detected: datetime, resolved: datetime | None
) -> None:
    resp = await api.post(
        "/api/v1/failures",
        json={
            "deployment_id": deployment_id,
            "severity": "sev2",
            "summary": "golden failure",
            "detected_at": detected.isoformat(),
            "resolved_at": resolved.isoformat() if resolved else None,
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.fixture
async def dataset_a(api: AsyncClient) -> str:
    """§12.1: returns the service id."""
    sid = str((await create_service(api, "golden-svc"))["id"])
    c0 = ("c000000", at(8, 29))
    c1 = ("c100000", at(9, 1))
    c2 = ("c200000", at(9, 4, 22))
    c3 = ("c300000", at(9, 9))
    c4 = ("c400000", at(9, 19, 20))
    c5 = ("c500000", at(9, 2))
    c6 = ("c600000", at(9, 11))

    await deploy(api, sid, at(8, 30), [c0])  # D0: before the window
    await deploy(api, sid, at(9, 2), [c1])  # D1
    d2 = await deploy(api, sid, at(9, 5), [c2, c0])  # D2: redeploys c0
    await deploy(api, sid, at(9, 10), [c3, c1], kind="remediation")  # D3: redeploys c1
    d4 = await deploy(api, sid, at(9, 20), [c4], status="rolled_back")  # D4
    await deploy(api, sid, at(9, 3), [c5], environment="staging")  # D5: wrong env
    await deploy(api, sid, at(9, 12), [c6], status="failed")  # D6: never live

    await fail(api, d2, at(9, 5, 12), at(9, 5, 15))  # F1: 3h
    await fail(api, d2, at(9, 6, 0), at(9, 6, 1))  # F2: 1h
    await fail(api, d4, at(9, 20, 11), None)  # F3: open
    return sid


EXPECTED_A: dict[str, Any] = {
    "band_set": "dora-2023-adapted",
    "deployment_frequency": {"count": 4, "per_day": 0.1333, "deploy_days": 4, "band": "medium"},
    "change_lead_time": {
        "median_hours": 19.0,
        "p90_hours": 24.0,
        "sample_size": 4,
        "excluded_samples": 0,
        "band": "elite",
    },
    "change_fail_rate": {
        "rate": 0.5,
        "failed_deployments": 2,
        "total_deployments": 4,
        "band": "low",
    },
    "failed_deployment_recovery_time": {
        "median_hours": 2.0,
        "sample_size": 2,
        "open_failures": 1,
        "band": "high",
    },
    "deployment_rework_rate": {
        "rate": 0.25,
        "remediation_deployments": 1,
        "total_deployments": 4,
        "band": None,
    },
}


async def test_golden_dataset_a_summary(api: AsyncClient, dataset_a: str) -> None:
    for service_filter in ({}, {"service_id": dataset_a}):
        resp = await api.get(SUMMARY, params={**WINDOW, **service_filter})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["window"] == {
            "from": "2026-09-01T00:00:00Z",
            "to": "2026-10-01T00:00:00Z",
            "days": 30.0,
        }
        assert body["filters"] == {
            "service_id": service_filter.get("service_id"),
            "environment": "production",
        }
        assert {k: v for k, v in body.items() if k not in ("window", "filters")} == EXPECTED_A


async def test_golden_dataset_a_weekly_timeseries(api: AsyncClient, dataset_a: str) -> None:
    resp = await api.get(SERIES, params={**WINDOW, "bucket": "week"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["bucket"] == "week"
    points = body["points"]
    # Mondays; the first bucket starts before `from` but counts in-window data only.
    assert [p["start"] for p in points] == [
        "2026-08-31T00:00:00Z",
        "2026-09-07T00:00:00Z",
        "2026-09-14T00:00:00Z",
        "2026-09-21T00:00:00Z",
        "2026-09-28T00:00:00Z",
    ]
    assert [p["deployment_count"] for p in points] == [2, 1, 1, 0, 0]
    assert [p["change_fail_rate"] for p in points] == [0.5, 0.0, 1.0, None, None]
    # c1 (24h) and c2 (12h) in week 1; c3 (24h) in week 2 (c1 was first live in D1); c4 (14h).
    assert [p["median_lead_time_hours"] for p in points] == [18.0, 24.0, 14.0, None, None]
    # F1 and F2 (D2, week 1) are resolved; F3 (D4, week 3) is open.
    assert [p["median_recovery_hours"] for p in points] == [2.0, None, None, None, None]
    assert [p["rework_rate"] for p in points] == [0.0, 1.0, 0.0, None, None]


async def test_other_bucket_sizes(api: AsyncClient, dataset_a: str) -> None:
    days = (await api.get(SERIES, params={**WINDOW, "bucket": "day"})).json()["points"]
    assert len(days) == 30
    assert days[0]["start"] == "2026-09-01T00:00:00Z"
    assert sum(p["deployment_count"] for p in days) == 4
    assert {p["start"][:10] for p in days if p["deployment_count"]} == {
        "2026-09-02",
        "2026-09-05",
        "2026-09-10",
        "2026-09-20",
    }

    months = (
        await api.get(
            SERIES,
            params={
                "from": "2026-08-15T00:00:00Z",
                "to": "2026-10-15T00:00:00Z",
                "bucket": "month",
            },
        )
    ).json()["points"]
    assert [p["start"] for p in months] == [
        "2026-08-01T00:00:00Z",
        "2026-09-01T00:00:00Z",
        "2026-10-01T00:00:00Z",
    ]
    # D0 (08-30) is in this wider window, so August has one deployment.
    assert [p["deployment_count"] for p in months] == [1, 4, 0]


async def test_golden_dataset_b_empty_window(api: AsyncClient, dataset_a: str) -> None:
    """§12.2: no counted deployments -> every value null, every count 0, every band null."""
    resp = await api.get(
        SUMMARY, params={"from": "2026-11-01T00:00:00Z", "to": "2026-12-01T00:00:00Z"}
    )
    body = resp.json()
    assert body["deployment_frequency"] == {
        "count": 0,
        "per_day": None,
        "deploy_days": 0,
        "band": None,
    }
    assert body["change_lead_time"] == {
        "median_hours": None,
        "p90_hours": None,
        "sample_size": 0,
        "excluded_samples": 0,
        "band": None,
    }
    assert body["change_fail_rate"] == {
        "rate": None,
        "failed_deployments": 0,
        "total_deployments": 0,
        "band": None,
    }
    assert body["failed_deployment_recovery_time"] == {
        "median_hours": None,
        "sample_size": 0,
        "open_failures": 0,
        "band": None,
    }
    assert body["deployment_rework_rate"] == {
        "rate": None,
        "remediation_deployments": 0,
        "total_deployments": 0,
        "band": None,
    }


async def test_golden_dataset_c_clock_skew(api: AsyncClient) -> None:
    """§12.3: a commit newer than its deployment is excluded, not counted as negative."""
    sid = str((await create_service(api, "skew-svc"))["id"])
    await deploy(api, sid, at(9, 10), [("5ce0000", at(9, 10, 12))])
    body = (await api.get(SUMMARY, params={**WINDOW, "service_id": sid})).json()
    assert body["change_lead_time"] == {
        "median_hours": None,
        "p90_hours": None,
        "sample_size": 0,
        "excluded_samples": 1,
        "band": None,
    }
    assert body["deployment_frequency"]["count"] == 1


async def test_service_filter_isolates_services(api: AsyncClient, dataset_a: str) -> None:
    other = str((await create_service(api, "other-svc"))["id"])
    await deploy(api, other, at(9, 15), [("0e00000", at(9, 14))])
    org = (await api.get(SUMMARY, params=WINDOW)).json()
    golden = (await api.get(SUMMARY, params={**WINDOW, "service_id": dataset_a})).json()
    only_other = (await api.get(SUMMARY, params={**WINDOW, "service_id": other})).json()
    assert org["deployment_frequency"]["count"] == 5
    assert golden["deployment_frequency"]["count"] == 4
    assert only_other["deployment_frequency"]["count"] == 1
    assert only_other["change_lead_time"]["median_hours"] == 24.0


async def test_bucketing_ignores_the_session_time_zone(api: AsyncClient, api_app: FastAPI) -> None:
    """date_trunc must use the explicit 'UTC' form (§7.8). Run the queries on a
    session set to New York: a deployment at Monday 02:00 UTC is still Sunday
    there, so a session-dependent query would put it in the previous week and
    count two deploy days where UTC has one."""
    sid = str((await create_service(api, "tz-svc"))["id"])
    await deploy(api, sid, at(9, 7, 2), [])  # Monday 02:00 UTC = Sunday 22:00 New York
    await deploy(api, sid, at(9, 7, 20), [])  # Monday 20:00 UTC = Monday 16:00 New York
    params = {
        "environment": "production",
        "from_ts": at(9, 1, 0),
        "to_ts": at(10, 1, 0),
        "service_id": None,
    }
    async with api_app.state.sessionmaker() as session:
        await session.execute(text("SET timezone TO 'America/New_York'"))
        row = await queries.summary(session, **params)  # type: ignore[arg-type]
        series = await queries.timeseries(session, **params, bucket="week")  # type: ignore[arg-type]
    assert row.deploy_days == 1
    counts = {b.start.astimezone(UTC).date().isoformat(): b.deployments for b in series}
    assert counts["2026-09-07"] == 2
    assert counts["2026-08-31"] == 0


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"from": "2026-09-10T00:00:00Z", "to": "2026-09-01T00:00:00Z"}, "from"),
        ({"from": "2025-01-01T00:00:00Z", "to": "2026-09-01T00:00:00Z"}, "to"),
        ({"from": "2026-09-01T00:00:00"}, "from"),  # naive
        ({"environment": "prod"}, "environment"),
        ({"service_id": "00000000-0000-7000-8000-000000000000"}, "service_id"),
        ({"bucket": "year"}, "bucket"),
    ],
)
async def test_invalid_queries_are_422(
    api: AsyncClient, params: dict[str, str], field: str
) -> None:
    url = SERIES if "bucket" in params else SUMMARY
    body = assert_problem(await api.get(url, params=params), 422)
    assert field in {e["field"] for e in body["errors"]}


async def test_defaults_are_production_and_last_30_days(api: AsyncClient) -> None:
    body = (await api.get(SUMMARY)).json()
    assert body["filters"]["environment"] == "production"
    assert body["window"]["days"] == 30.0
    series = (await api.get(SERIES)).json()
    assert series["bucket"] == "week"
    assert 5 <= len(series["points"]) <= 6
