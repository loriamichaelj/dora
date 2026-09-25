"""DORA metrics: window rules, SQL aggregates, and band classification (§3, §7.8)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.dora import queries
from app.dora.bands import DEFAULT_BAND_SET, BandSet
from app.dora.classify import classify, ratio, round_hours, round_rate
from app.problems import Unprocessable, field_error
from app.repositories import services as services_repo
from app.schemas.metrics import (
    ChangeFailRate,
    ChangeLeadTime,
    DeploymentFrequency,
    DoraSummary,
    DoraTimeseries,
    Filters,
    RecoveryTime,
    ReworkRate,
    TimeseriesPoint,
    Window,
)

DEFAULT_WINDOW = timedelta(days=30)
MAX_WINDOW = timedelta(days=365)
SECONDS_PER_DAY = 86_400


@dataclass(frozen=True)
class Query:
    environment: str
    from_ts: datetime
    to_ts: datetime
    service_id: uuid.UUID | None

    @property
    def days(self) -> float:
        return (self.to_ts - self.from_ts).total_seconds() / SECONDS_PER_DAY

    def window(self) -> Window:
        return Window(from_=self.from_ts, to=self.to_ts, days=round(self.days, 4))

    def filters(self) -> Filters:
        return Filters(service_id=self.service_id, environment=self.environment)


def resolve_window(
    from_ts: datetime | None, to_ts: datetime | None, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """Default: the 30 days ending now (or ending at `to`). Max span 365 days."""
    to_ts = to_ts or now or datetime.now(UTC)
    from_ts = from_ts or to_ts - DEFAULT_WINDOW
    if from_ts >= to_ts:
        raise Unprocessable(
            "The window is empty: 'from' must be before 'to'.",
            errors=[field_error("from", "Must be before 'to'.", location="query", type_="order")],
        )
    if to_ts - from_ts > MAX_WINDOW:
        raise Unprocessable(
            "The window may span at most 365 days.",
            errors=[field_error("to", "Window exceeds 365 days.", location="query", type_="span")],
        )
    return from_ts.astimezone(UTC), to_ts.astimezone(UTC)


async def build_query(
    session: AsyncSession,
    *,
    environment: str,
    from_ts: datetime | None,
    to_ts: datetime | None,
    service_id: uuid.UUID | None,
) -> Query:
    start, end = resolve_window(from_ts, to_ts)
    if service_id is not None and await services_repo.get(session, service_id) is None:
        raise Unprocessable(
            f"No service with id {service_id}.",
            errors=[
                field_error(
                    "service_id", "No service with this id.", location="query", type_="not_found"
                )
            ],
        )
    return Query(environment=environment, from_ts=start, to_ts=end, service_id=service_id)


async def summary(
    session: AsyncSession, query: Query, band_set: BandSet = DEFAULT_BAND_SET
) -> DoraSummary:
    row = await queries.summary(
        session,
        environment=query.environment,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        service_id=query.service_id,
    )
    total = row.deployments
    per_day = total / query.days if total else None
    fail_rate = ratio(row.failed_deployments, total)
    return DoraSummary(
        window=query.window(),
        filters=query.filters(),
        band_set=band_set.name,
        deployment_frequency=DeploymentFrequency(
            count=total,
            per_day=round_rate(per_day),
            deploy_days=row.deploy_days,
            band=classify(band_set, "deployment_frequency", per_day),
        ),
        change_lead_time=ChangeLeadTime(
            median_hours=round_hours(row.lead_median_hours),
            p90_hours=round_hours(row.lead_p90_hours),
            sample_size=row.lead_samples,
            excluded_samples=row.lead_excluded,
            band=classify(band_set, "change_lead_time", row.lead_median_hours),
        ),
        change_fail_rate=ChangeFailRate(
            rate=round_rate(fail_rate),
            failed_deployments=row.failed_deployments,
            total_deployments=total,
            band=classify(band_set, "change_fail_rate", fail_rate),
        ),
        failed_deployment_recovery_time=RecoveryTime(
            median_hours=round_hours(row.recovery_median_hours),
            sample_size=row.recovery_samples,
            open_failures=row.open_failures,
            band=classify(band_set, "failed_deployment_recovery_time", row.recovery_median_hours),
        ),
        deployment_rework_rate=ReworkRate(
            rate=round_rate(ratio(row.remediation_deployments, total)),
            remediation_deployments=row.remediation_deployments,
            total_deployments=total,
            band=None,
        ),
    )


async def timeseries(session: AsyncSession, query: Query, bucket: queries.Bucket) -> DoraTimeseries:
    rows = await queries.timeseries(
        session,
        environment=query.environment,
        from_ts=query.from_ts,
        to_ts=query.to_ts,
        service_id=query.service_id,
        bucket=bucket,
    )
    return DoraTimeseries(
        window=query.window(),
        filters=query.filters(),
        bucket=bucket,
        points=[
            TimeseriesPoint(
                start=row.start,
                deployment_count=row.deployments,
                median_lead_time_hours=round_hours(row.lead_median_hours),
                change_fail_rate=round_rate(ratio(row.failed_deployments, row.deployments)),
                median_recovery_hours=round_hours(row.recovery_median_hours),
                rework_rate=round_rate(ratio(row.remediation_deployments, row.deployments)),
            )
            for row in rows
        ],
    )
