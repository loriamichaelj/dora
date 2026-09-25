"""Deterministic demo data: `python -m app.seed --days 90 --seed 42 [--large]` (§10).

The same --seed, --days, and --end always produce the same rows, including
UUIDs and SHAs. Generation is pure (`generate`); writing (`write`) replaces
only seed-managed services, so re-seeding never duplicates data and never
touches anything else, such as the self-tracking `dora-tracker` service.

Profiles (§10):
  checkout-api    several deploys a day, low fail rate, fast recovery, ~3% remediation
  catalog-svc     roughly daily, moderate metrics
  payments-gw     weekly, occasional sev1, ~15% remediation
  legacy-billing  monthly, high fail rate, slow recovery, ~30% remediation
  search-indexer  staging-heavy, few production deploys
  new-svc         no deployments (exercises empty states)
--large adds 40 `load-svc-NN` services for ~100k deployments (§12 performance).
"""

import argparse
import asyncio
import math
import random
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

import structlog
from sqlalchemy import text

from app.config import DatabaseSettings, get_database_settings
from app.db import create_engine
from app.logging import configure_logging

log = structlog.get_logger("app.seed")

MANAGED_SLUG_PATTERN = "load-svc-%"


@dataclass(frozen=True)
class Profile:
    slug: str
    name: str
    owner_team: str
    prod_per_day: float
    staging_before_prod: bool = True  # each prod deploy goes to staging first
    extra_staging_per_day: float = 0.0
    pipeline_fail_rate: float = 0.02  # never went live
    change_fail_rate: float = 0.05
    rework_rate: float = 0.05
    commits_per_deploy: tuple[int, int] = (1, 3)
    lead_hours_median: float = 24.0
    recovery_hours_median: float = 4.0
    sev1_share: float = 0.1


PROFILES: tuple[Profile, ...] = (
    Profile(
        "checkout-api", "Checkout API", "payments", prod_per_day=4.0,
        change_fail_rate=0.03, rework_rate=0.03, commits_per_deploy=(1, 3),
        lead_hours_median=6.0, recovery_hours_median=0.5, sev1_share=0.05,
    ),
    Profile(
        "catalog-svc", "Catalog Service", "catalog", prod_per_day=1.0,
        change_fail_rate=0.12, rework_rate=0.08, commits_per_deploy=(2, 5),
        lead_hours_median=30.0, recovery_hours_median=6.0,
    ),
    Profile(
        "payments-gw", "Payments Gateway", "payments", prod_per_day=1 / 7,
        change_fail_rate=0.2, rework_rate=0.15, commits_per_deploy=(5, 12),
        lead_hours_median=96.0, recovery_hours_median=12.0, sev1_share=0.5,
    ),
    Profile(
        "legacy-billing", "Legacy Billing", "finance", prod_per_day=1 / 30,
        pipeline_fail_rate=0.0, change_fail_rate=0.6, rework_rate=0.3,
        commits_per_deploy=(10, 25), lead_hours_median=400.0,
        recovery_hours_median=72.0, sev1_share=0.3,
    ),
    Profile(
        "search-indexer", "Search Indexer", "search", prod_per_day=1 / 10,
        extra_staging_per_day=3.0, change_fail_rate=0.1, rework_rate=0.05,
        lead_hours_median=48.0, recovery_hours_median=3.0,
    ),
    Profile("new-svc", "New Service", "platform", prod_per_day=0.0, staging_before_prod=False),
)  # fmt: skip

LOAD_SERVICES = 40
LOAD_PROFILE = Profile(
    "load-svc-00", "Load Service", "load", prod_per_day=25.0, staging_before_prod=False,
    extra_staging_per_day=2.5, change_fail_rate=0.08, rework_rate=0.05,
    commits_per_deploy=(1, 2), lead_hours_median=12.0, recovery_hours_median=2.0,
)  # fmt: skip


# ---- rows (plain tuples in COPY column order) ----

SERVICE_COLUMNS = ("id", "slug", "name", "owner_team", "repo_url")
DEPLOYMENT_COLUMNS = (
    "id", "service_id", "environment", "kind", "release", "head_sha", "status",
    "started_at", "finished_at", "deployed_by", "pipeline_url", "external_id",
)  # fmt: skip
COMMIT_COLUMNS = ("id", "service_id", "sha", "committed_at", "author", "message")
LINK_COLUMNS = ("deployment_id", "commit_id")
FAILURE_COLUMNS = ("id", "deployment_id", "severity", "summary", "detected_at", "resolved_at")

AUTHORS = ("ana@example.com", "bo@example.com", "chen@example.com", "dee@example.com")
SUBJECTS = ("fix", "feat", "chore", "refactor", "perf", "docs")
SYMPTOMS = ("error rate spike", "latency regression", "failed health checks", "5xx burst")


@dataclass
class Dataset:
    services: list[tuple[object, ...]] = field(default_factory=list)
    deployments: list[tuple[object, ...]] = field(default_factory=list)
    commits: list[tuple[object, ...]] = field(default_factory=list)
    links: list[tuple[object, ...]] = field(default_factory=list)
    failures: list[tuple[object, ...]] = field(default_factory=list)

    @property
    def slugs(self) -> list[str]:
        return [str(row[1]) for row in self.services]

    def counts(self) -> dict[str, int]:
        return {
            "services": len(self.services),
            "deployments": len(self.deployments),
            "commits": len(self.commits),
            "deployment_commits": len(self.links),
            "failures": len(self.failures),
        }


def uuid7(at: datetime, rng: random.Random) -> uuid.UUID:
    """A valid, time-ordered UUIDv7 whose random bits come from `rng`, so
    seeded IDs are deterministic (RFC 9562 layout)."""
    millis = int(at.timestamp() * 1000) & ((1 << 48) - 1)
    value = (millis << 80) | (0x7 << 76) | (rng.getrandbits(12) << 64)
    value |= (0b10 << 62) | rng.getrandbits(62)
    return uuid.UUID(int=value)


class _Diffuser:
    """Fires at a steady long-run rate instead of by independent coin flips.

    With a random starting phase, n draws fire round(n * rate) times, give or
    take one, spread evenly. Small samples (a monthly service has three deploys
    in 90 days) then still show their profile, and every 30-day window sees
    roughly the configured rate."""

    def __init__(self, rate: float, rng: random.Random) -> None:
        self.rate = rate
        self.level = rng.random()

    def fires(self) -> bool:
        self.level += self.rate
        if self.level >= 1.0:
            self.level -= 1.0
            return True
        return False


class _ServiceGenerator:
    def __init__(self, profile: Profile, rng: random.Random, start: datetime, end: datetime):
        self.p = profile
        self.rng = rng
        self.start = start
        self.end = end
        self.data = Dataset()
        self.service_id = uuid7(start, rng)
        # Commits not yet shipped to each environment. A deployment links the
        # commits new to its environment since that environment's last deploy.
        self.pending: dict[str, list[tuple[uuid.UUID, str]]] = {"staging": [], "production": []}
        self.sequence = 0
        self.pipeline_fails = _Diffuser(profile.pipeline_fail_rate, rng)
        self.change_fails = _Diffuser(profile.change_fail_rate, rng)
        self.remediations = _Diffuser(profile.rework_rate, rng)

    def _hours(self, median: float, spread: float = 0.6) -> float:
        return self.rng.lognormvariate(math.log(median), spread)

    def _sha(self) -> str:
        return f"{self.rng.getrandbits(160):040x}"

    def _schedule(self, per_day: float) -> list[datetime]:
        """Evenly spaced with jitter: sparse services still deploy regularly,
        so every 30-day window sees their profile."""
        days = (self.end - self.start).total_seconds() / 86_400
        count = round(days * per_day)
        if count == 0:
            return []
        gap = timedelta(days=days / count)
        return sorted(self.end - gap * (i + self.rng.uniform(0.15, 0.85)) for i in range(count))

    def _add_commits(self, before: datetime) -> None:
        low, high = self.p.commits_per_deploy
        for _ in range(self.rng.randint(low, high)):
            committed = before - timedelta(hours=self._hours(self.p.lead_hours_median))
            commit_id = uuid7(committed, self.rng)
            sha = self._sha()
            subject = f"{self.rng.choice(SUBJECTS)}: change {sha[:7]}"
            self.data.commits.append(
                (commit_id, self.service_id, sha, committed, self.rng.choice(AUTHORS), subject)
            )
            for queue in self.pending.values():
                queue.append((commit_id, sha))

    def _deployment(
        self, finished: datetime, environment: str, *, status: str, kind: str = "planned"
    ) -> uuid.UUID:
        self.sequence += 1
        started = finished - timedelta(minutes=self.rng.uniform(3, 15))
        deployment_id = uuid7(started, self.rng)
        pending = self.pending[environment]
        head = pending[-1][1] if pending else None
        run = 10_000_000 + self.sequence
        self.data.deployments.append(
            (
                deployment_id, self.service_id, environment, kind,
                f"v1.{self.sequence // 50}.{self.sequence % 50}", head, status,
                started, None if status == "in_progress" else finished, "github-actions",
                f"https://github.com/example/{self.p.slug}/actions/runs/{run}",
                f"seed-{self.p.slug}-{environment}-{self.sequence:06d}",
            )
        )  # fmt: skip
        for commit_id, _ in pending:
            self.data.links.append((deployment_id, commit_id))
        if status in ("succeeded", "rolled_back"):
            pending.clear()  # a failed pipeline leaves them to ship next time
        return deployment_id

    def _maybe_fail(self, deployment_id: uuid.UUID, finished: datetime) -> bool:
        if not self.change_fails.fires():
            return False
        detected = finished + timedelta(minutes=self.rng.uniform(5, 180))
        recovery = timedelta(hours=self._hours(self.p.recovery_hours_median))
        recent = self.end - detected < timedelta(days=2)
        resolved = None if recent and self.rng.random() < 0.5 else detected + recovery
        severity = (
            "sev1"
            if self.rng.random() < self.p.sev1_share
            else self.rng.choice(("sev2", "sev3", "sev4"))
        )
        self.data.failures.append(
            (
                uuid7(detected, self.rng), deployment_id, severity,
                f"{self.p.name}: {self.rng.choice(SYMPTOMS)}", detected, resolved,
            )
        )  # fmt: skip
        return True

    def run(self, service_row: tuple[object, ...]) -> Dataset:
        self.data.services.append(service_row)
        events = [(t, "production") for t in self._schedule(self.p.prod_per_day)]
        events += [(t, "staging") for t in self._schedule(self.p.extra_staging_per_day)]
        for finished, environment in sorted(events):
            if environment == "staging":
                self._add_commits(before=finished - timedelta(minutes=30))
                self._deployment(finished, "staging", status="succeeded")
                continue
            staged_at = finished - timedelta(hours=self.rng.uniform(1, 6))
            # Commits always predate the first deployment that ships them.
            self._add_commits(before=staged_at - timedelta(minutes=30))
            if self.p.staging_before_prod:
                self._deployment(staged_at, "staging", status="succeeded")
            if self.pipeline_fails.fires():
                self._deployment(finished, "production", status="failed")
                continue
            kind = "remediation" if self.remediations.fires() else "planned"
            deployment_id = self._deployment(finished, "production", status="succeeded", kind=kind)
            if self._maybe_fail(deployment_id, finished) and self.rng.random() < 0.4:
                row = self.data.deployments[-1]
                self.data.deployments[-1] = (*row[:6], "rolled_back", *row[7:])
        return self.data


def generate(*, seed: int, days: int, end: datetime, large: bool = False) -> Dataset:
    rng = random.Random(seed)
    start = end - timedelta(days=days)
    profiles = list(PROFILES)
    if large:
        profiles += [
            Profile(
                **{**LOAD_PROFILE.__dict__, "slug": f"load-svc-{n:02d}", "name": f"Load {n:02d}"}
            )
            for n in range(1, LOAD_SERVICES + 1)
        ]
    dataset = Dataset()
    for profile in profiles:
        generator = _ServiceGenerator(profile, random.Random(rng.getrandbits(64)), start, end)
        service_row = (
            generator.service_id, profile.slug, profile.name, profile.owner_team,
            f"https://github.com/example/{profile.slug}",
        )  # fmt: skip
        part = generator.run(service_row)
        for name in ("services", "deployments", "commits", "links", "failures"):
            getattr(dataset, name).extend(getattr(part, name))

    # checkout-api has one deployment in flight at the end of the window.
    checkout = next(row for row in dataset.services if row[1] == "checkout-api")
    in_flight = end - timedelta(minutes=5)
    dataset.deployments.append(
        (
            uuid7(in_flight, rng), checkout[0], "production", "planned", "v2.0.0-rc.1", None,
            "in_progress", in_flight, None, "github-actions",
            "https://github.com/example/checkout-api/actions/runs/99999999",
            "seed-checkout-api-production-in-flight",
        )
    )  # fmt: skip
    return dataset


# Seed-managed services are the profile slugs plus load-svc-*. Children first.
_DELETE_MANAGED = (
    """DELETE FROM dora.failures WHERE deployment_id IN (
         SELECT d.id FROM dora.deployments d JOIN dora.services s ON s.id = d.service_id
          WHERE s.slug = ANY(:slugs) OR s.slug LIKE :pattern)""",
    """DELETE FROM dora.deployments WHERE service_id IN (
         SELECT id FROM dora.services WHERE slug = ANY(:slugs) OR slug LIKE :pattern)""",
    """DELETE FROM dora.commits WHERE service_id IN (
         SELECT id FROM dora.services WHERE slug = ANY(:slugs) OR slug LIKE :pattern)""",
    "DELETE FROM dora.services WHERE slug = ANY(:slugs) OR slug LIKE :pattern",
)


async def write(dataset: Dataset, settings: DatabaseSettings | None = None) -> None:
    """Replace all seed-managed data in one transaction, via COPY."""
    engine = create_engine(settings or get_database_settings(), null_pool=True)
    try:
        async with engine.begin() as conn:
            params = {"slugs": [p.slug for p in PROFILES], "pattern": MANAGED_SLUG_PATTERN}
            for statement in _DELETE_MANAGED:
                await conn.execute(text(statement), params)

            raw = (await conn.get_raw_connection()).driver_connection
            assert raw is not None
            for table, columns, rows in (
                ("services", SERVICE_COLUMNS, dataset.services),
                ("deployments", DEPLOYMENT_COLUMNS, dataset.deployments),
                ("commits", COMMIT_COLUMNS, dataset.commits),
                ("deployment_commits", LINK_COLUMNS, dataset.links),
                ("failures", FAILURE_COLUMNS, dataset.failures),
            ):
                await raw.copy_records_to_table(
                    table, records=rows, columns=list(columns), schema_name="dora"
                )
    finally:
        await engine.dispose()


def default_end() -> datetime:
    """Midnight UTC today: the same day always yields the same data."""
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.seed", description="Load deterministic DORA demo data."
    )
    parser.add_argument("--days", type=int, default=90, help="history length (default 90)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument(
        "--end",
        type=date.fromisoformat,
        help="last day, exclusive, as YYYY-MM-DD (default: today, UTC)",
    )
    parser.add_argument("--large", action="store_true", help="add ~100k deployments")
    args = parser.parse_args(argv)
    if not 1 <= args.days <= 365:
        parser.error("--days must be between 1 and 365")

    configure_logging()
    end = datetime.combine(args.end, time.min, tzinfo=UTC) if args.end else default_end()
    dataset = generate(seed=args.seed, days=args.days, end=end, large=args.large)
    asyncio.run(write(dataset))
    log.info("seeded", seed=args.seed, days=args.days, end=end.isoformat(), **dataset.counts())
    return 0


if __name__ == "__main__":
    sys.exit(main())
