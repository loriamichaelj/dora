"""DORA metric SQL (§3, §7.8). All aggregation happens in PostgreSQL.

Definitions, for one environment and a window [from, to) in UTC:
- live deployment:    status IN ('succeeded', 'rolled_back')
- counted deployment: a live deployment in the environment whose finished_at
                      is in the window
- lead-time sample:   per commit, first_live.finished_at - committed_at, where
                      first_live is the commit's earliest live deployment in the
                      environment across ALL time. Only commits whose first_live
                      is a counted deployment are samples (D13). Negative
                      samples (clock skew) are excluded and counted.

Time-series buckets are `date_trunc(bucket, ts, 'UTC')` with the explicit
time zone, so they never depend on the session setting. A deployment's
facts land in the bucket of its finished_at; a lead-time sample lands in the
bucket of its first_live deployment (D43).

Safety: the SQL strings are assembled only from constants in this module (the
live-status list and one fixed service-filter fragment). Every value is a
bound parameter. The service filter is added or omitted rather than written as
`(:id IS NULL OR ...)`, which would defeat index use under generic plans.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

Bucket = Literal["day", "week", "month"]

_LIVE = "('succeeded', 'rolled_back')"


def _counted_cte(service_filter: str) -> str:
    return f"""
    counted AS (
        SELECT d.id, d.finished_at, d.kind,
               EXISTS (SELECT 1 FROM dora.failures f WHERE f.deployment_id = d.id) AS has_failure
          FROM dora.deployments d
         WHERE d.environment = :environment
           AND d.status IN {_LIVE}
           AND d.finished_at >= :from_ts AND d.finished_at < :to_ts
           {service_filter}
    )"""


def _lead_time_ctes(service_filter: str) -> str:
    # Only commits shipped by a counted deployment can be samples, so start
    # from those, then find each one's first live deployment across all time.
    return f"""
    candidate_commits AS (
        SELECT DISTINCT dc.commit_id
          FROM dora.deployment_commits dc
          JOIN counted c ON c.id = dc.deployment_id
    ),
    first_live AS (
        SELECT dc.commit_id, min(d.finished_at) AS first_finished_at
          FROM candidate_commits cc
          JOIN dora.deployment_commits dc ON dc.commit_id = cc.commit_id
          JOIN dora.deployments d ON d.id = dc.deployment_id
         WHERE d.environment = :environment
           AND d.status IN {_LIVE}
           {service_filter}
         GROUP BY dc.commit_id
    ),
    lead_samples AS (
        SELECT fl.first_finished_at,
               CAST(
                   EXTRACT(EPOCH FROM (fl.first_finished_at - cm.committed_at)) / 3600
                   AS double precision
               ) AS hours
          FROM first_live fl
          JOIN dora.commits cm ON cm.id = fl.commit_id
         WHERE fl.first_finished_at >= :from_ts AND fl.first_finished_at < :to_ts
    )"""


def _recovery_cte() -> str:
    return """
    recovery AS (
        SELECT c.finished_at AS deployment_finished_at,
               f.resolved_at IS NULL AS is_open,
               CAST(EXTRACT(EPOCH FROM (f.resolved_at - f.detected_at)) / 3600 AS double precision)
                   AS hours
          FROM dora.failures f
          JOIN counted c ON c.id = f.deployment_id
    )"""


def _params(
    environment: str, from_ts: datetime, to_ts: datetime, service_id: uuid.UUID | None
) -> tuple[str, dict[str, object]]:
    params: dict[str, object] = {"environment": environment, "from_ts": from_ts, "to_ts": to_ts}
    if service_id is None:
        return "", params
    params["service_id"] = service_id
    return "AND d.service_id = :service_id", params


@dataclass(frozen=True)
class SummaryRow:
    deployments: int
    deploy_days: int
    failed_deployments: int
    remediation_deployments: int
    lead_median_hours: float | None
    lead_p90_hours: float | None
    lead_samples: int
    lead_excluded: int
    recovery_median_hours: float | None
    recovery_samples: int
    open_failures: int


async def summary(
    session: AsyncSession,
    *,
    environment: str,
    from_ts: datetime,
    to_ts: datetime,
    service_id: uuid.UUID | None,
) -> SummaryRow:
    service_filter, params = _params(environment, from_ts, to_ts, service_id)
    sql = f"""
    WITH {_counted_cte(service_filter)},
    {_lead_time_ctes(service_filter)},
    {_recovery_cte()}
    SELECT
        (SELECT count(*) FROM counted) AS deployments,
        (SELECT count(DISTINCT date_trunc('day', finished_at, 'UTC')) FROM counted) AS deploy_days,
        (SELECT count(*) FILTER (WHERE has_failure) FROM counted) AS failed_deployments,
        (SELECT count(*) FILTER (WHERE kind = 'remediation') FROM counted)
            AS remediation_deployments,
        (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY hours)
           FROM lead_samples WHERE hours >= 0) AS lead_median_hours,
        (SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY hours)
           FROM lead_samples WHERE hours >= 0) AS lead_p90_hours,
        (SELECT count(*) FROM lead_samples WHERE hours >= 0) AS lead_samples,
        (SELECT count(*) FROM lead_samples WHERE hours < 0) AS lead_excluded,
        (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY hours)
           FROM recovery WHERE NOT is_open) AS recovery_median_hours,
        (SELECT count(*) FROM recovery WHERE NOT is_open) AS recovery_samples,
        (SELECT count(*) FROM recovery WHERE is_open) AS open_failures
    """
    row = (await session.execute(text(sql), params)).one()
    return SummaryRow(**row._asdict())


@dataclass(frozen=True)
class BucketRow:
    start: datetime
    deployments: int
    failed_deployments: int
    remediation_deployments: int
    lead_median_hours: float | None
    recovery_median_hours: float | None


_STEP = {"day": "1 day", "week": "1 week", "month": "1 month"}


async def timeseries(
    session: AsyncSession,
    *,
    environment: str,
    from_ts: datetime,
    to_ts: datetime,
    service_id: uuid.UUID | None,
    bucket: Bucket,
) -> list[BucketRow]:
    service_filter, params = _params(environment, from_ts, to_ts, service_id)
    params["bucket"] = bucket
    params["step"] = _STEP[bucket]
    sql = f"""
    WITH {_counted_cte(service_filter)},
    {_lead_time_ctes(service_filter)},
    {_recovery_cte()},
    buckets AS (
        -- Every bucket overlapping the window, empty ones included. The first
        -- one can start before `from`; only in-window data is ever counted.
        SELECT b AS start
          FROM generate_series(
                   date_trunc(:bucket, CAST(:from_ts AS timestamptz), 'UTC'),
                   CAST(:to_ts AS timestamptz),
                   CAST(CAST(:step AS text) AS interval),  -- "1 month" has no timedelta
                   'UTC'
               ) AS b
         WHERE b < :to_ts
    ),
    deployment_agg AS (
        SELECT date_trunc(:bucket, finished_at, 'UTC') AS start,
               count(*) AS deployments,
               count(*) FILTER (WHERE has_failure) AS failed_deployments,
               count(*) FILTER (WHERE kind = 'remediation') AS remediation_deployments
          FROM counted
         GROUP BY 1
    ),
    lead_agg AS (
        SELECT date_trunc(:bucket, first_finished_at, 'UTC') AS start,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY hours) AS lead_median_hours
          FROM lead_samples
         WHERE hours >= 0
         GROUP BY 1
    ),
    recovery_agg AS (
        SELECT date_trunc(:bucket, deployment_finished_at, 'UTC') AS start,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY hours) AS recovery_median_hours
          FROM recovery
         WHERE NOT is_open
         GROUP BY 1
    )
    SELECT b.start,
           coalesce(d.deployments, 0) AS deployments,
           coalesce(d.failed_deployments, 0) AS failed_deployments,
           coalesce(d.remediation_deployments, 0) AS remediation_deployments,
           l.lead_median_hours,
           r.recovery_median_hours
      FROM buckets b
      LEFT JOIN deployment_agg d ON d.start = b.start
      LEFT JOIN lead_agg l ON l.start = b.start
      LEFT JOIN recovery_agg r ON r.start = b.start
     ORDER BY b.start
    """
    rows = (await session.execute(text(sql), params)).all()
    return [BucketRow(**row._asdict()) for row in rows]
