"""The seed generator is deterministic and only ever produces valid data (§10)."""

import re
import uuid
from collections import Counter
from datetime import UTC, datetime

import pytest

from app.seed import Dataset, generate

END = datetime(2026, 9, 25, tzinfo=UTC)
SHA = re.compile(r"^[0-9a-f]{7,40}$")
LIVE = {"succeeded", "rolled_back"}


@pytest.fixture(scope="module")
def normal() -> Dataset:
    return generate(seed=42, days=90, end=END)


@pytest.fixture(scope="module")
def large() -> Dataset:
    return generate(seed=42, days=90, end=END, large=True)


def test_same_inputs_same_rows(normal: Dataset) -> None:
    again = generate(seed=42, days=90, end=END)
    assert again == normal


def test_different_seed_different_rows(normal: Dataset) -> None:
    other = generate(seed=7, days=90, end=END)
    assert other.deployments != normal.deployments


def test_large_is_about_100k_deployments(large: Dataset) -> None:
    assert 95_000 <= len(large.deployments) <= 105_000


@pytest.mark.parametrize("name", ["normal", "large"])
def test_every_row_satisfies_the_schema_and_business_rules(
    name: str, request: pytest.FixtureRequest
) -> None:
    data: Dataset = request.getfixturevalue(name)
    services = {row[0]: row for row in data.services}
    deployments = {row[0]: row for row in data.deployments}
    commits = {row[0]: row for row in data.commits}

    all_ids = [*services, *deployments, *commits, *(f[0] for f in data.failures)]
    assert len(all_ids) == len(set(all_ids))
    assert all(isinstance(i, uuid.UUID) and i.version == 7 for i in all_ids)

    assert len({(d[1], d[11]) for d in data.deployments}) == len(data.deployments)
    assert len({(c[1], c[2]) for c in data.commits}) == len(data.commits)
    assert len(set(data.links)) == len(data.links)

    for d in data.deployments:
        _, service_id, env, kind, release, head, status, started, finished, *_ = d
        assert service_id in services
        assert env in {"development", "staging", "production"}
        assert kind in {"planned", "remediation"}
        assert 1 <= len(str(release)) <= 100
        assert head is None or SHA.match(str(head))
        if status == "in_progress":
            assert finished is None
        else:
            assert status in {"succeeded", "failed", "rolled_back"}
            assert finished is not None
            assert finished >= started

    for c in data.commits:
        assert SHA.match(str(c[2]))
        assert c[1] in services

    for deployment_id, commit_id in data.links:
        deployment, commit = deployments[deployment_id], commits[commit_id]
        assert deployment[1] == commit[1]  # same service
        assert commit[3] <= deployment[8]  # committed before it shipped: no skew

    for f in data.failures:
        deployment = deployments[f[1]]
        assert deployment[6] in LIVE
        assert f[2] in {"sev1", "sev2", "sev3", "sev4"}
        assert f[4] >= deployment[8]
        assert f[5] is None or f[5] >= f[4]


def test_profiles_have_their_shape(normal: Dataset) -> None:
    slug = {row[0]: row[1] for row in normal.services}
    prod = Counter(slug[d[1]] for d in normal.deployments if d[2] == "production")
    staging = Counter(slug[d[1]] for d in normal.deployments if d[2] == "staging")
    remediation = Counter(
        slug[d[1]] for d in normal.deployments if d[2] == "production" and d[3] == "remediation"
    )

    assert set(slug.values()) == {
        "checkout-api",
        "catalog-svc",
        "payments-gw",
        "legacy-billing",
        "search-indexer",
        "new-svc",
    }
    assert prod["checkout-api"] >= 90 * 3  # several a day
    assert 80 <= prod["catalog-svc"] <= 100  # roughly daily
    assert 11 <= prod["payments-gw"] <= 15  # weekly
    assert prod["legacy-billing"] == 3  # monthly over 90 days
    assert staging["search-indexer"] > 10 * prod["search-indexer"]  # staging-heavy
    assert prod["new-svc"] == staging["new-svc"] == 0  # empty states
    assert remediation["checkout-api"] / prod["checkout-api"] < 0.1
    assert "dora-tracker" not in slug.values()  # created only by self-tracking (§15.5)


@pytest.mark.parametrize("seed", range(20))
def test_legacy_billing_fail_rate_is_low_band_for_any_seed(seed: int) -> None:
    """Error diffusion makes the realized rate track the profile even with
    three deployments, so E2E scenario 9 doesn't depend on a lucky seed."""
    data = generate(seed=seed, days=90, end=END)
    [legacy] = [row[0] for row in data.services if row[1] == "legacy-billing"]
    live = [
        d[0] for d in data.deployments
        if d[1] == legacy and d[2] == "production" and d[6] in LIVE
    ]  # fmt: skip
    failed = {f[1] for f in data.failures} & set(live)
    assert len(live) == 3
    assert len(failed) / len(live) > 0.15  # the "low" band for change fail rate
