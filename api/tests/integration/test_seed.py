"""Seeding a real database: E2E scenario 9's expectations, idempotent re-seeding,
and no collateral damage to non-seed services (§10, §12.4, §15.5)."""

from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.seed import generate, write
from tests.integration.conftest import Database
from tests.integration.helpers import create_service

END = datetime(2026, 9, 25, tzinfo=UTC)
# E2E scenario 9 reads bands over the seed's whole 90-day history: a monthly
# service like legacy-billing has about one deploy in any 30-day window, so its
# fail rate there can only be 0 or 1 (D57).
SEED_WINDOW = {"from": (END - timedelta(days=90)).isoformat(), "to": END.isoformat()}


COUNTS_SQL = text(
    "SELECT (SELECT count(*) FROM dora.services) AS services,"
    " (SELECT count(*) FROM dora.deployments) AS deployments,"
    " (SELECT count(*) FROM dora.commits) AS commits,"
    " (SELECT count(*) FROM dora.deployment_commits) AS deployment_commits,"
    " (SELECT count(*) FROM dora.failures) AS failures"
)


async def table_counts(engine: AsyncEngine) -> dict[str, int]:
    async with engine.connect() as conn:
        row = (await conn.execute(COUNTS_SQL)).one()
    return dict(row._asdict())


async def summary_for(api: AsyncClient, slug: str) -> dict[str, Any]:
    services = (await api.get("/api/v1/services", params={"q": slug})).json()["items"]
    [service] = [s for s in services if s["slug"] == slug]
    resp = await api.get(
        "/api/v1/metrics/dora", params={**SEED_WINDOW, "service_id": service["id"]}
    )
    assert resp.status_code == 200, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def test_seeded_profiles_show_through_the_api(
    api: AsyncClient, migrated: Database, owner_engine: AsyncEngine
) -> None:
    tracker = await create_service(api, "dora-tracker", owner_team="platform")
    dataset = generate(seed=42, days=90, end=END)
    await write(dataset, migrated.app)

    # E2E scenario 9.
    checkout = await summary_for(api, "checkout-api")
    assert checkout["deployment_frequency"]["band"] == "elite"
    legacy = await summary_for(api, "legacy-billing")
    assert legacy["change_fail_rate"]["band"] == "low"
    new_svc = await summary_for(api, "new-svc")
    assert new_svc["deployment_frequency"]["count"] == 0
    assert new_svc["change_lead_time"]["median_hours"] is None
    assert all(
        new_svc[metric]["band"] is None
        for metric in (
            "deployment_frequency",
            "change_lead_time",
            "change_fail_rate",
            "failed_deployment_recovery_time",
        )
    )

    # Re-seeding replaces rather than duplicates, and leaves other services alone.
    before = await table_counts(owner_engine)
    await write(generate(seed=42, days=90, end=END), migrated.app)
    assert await table_counts(owner_engine) == before
    assert before["services"] == len(dataset.services) + 1  # + dora-tracker
    assert (await api.get(f"/api/v1/services/{tracker['id']}")).status_code == 200


async def test_large_seed_can_be_replaced_by_a_normal_one(
    api: AsyncClient, migrated: Database, owner_engine: AsyncEngine
) -> None:
    """Load services from --large are seed-managed too, so a later normal seed removes them."""
    small = generate(seed=1, days=3, end=END, large=True)
    await write(small, migrated.app)
    assert (await table_counts(owner_engine))["services"] == len(small.services)

    await write(generate(seed=1, days=3, end=END), migrated.app)
    counts = await table_counts(owner_engine)
    assert counts["services"] == 6
