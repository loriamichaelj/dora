"""Response shapes for /api/v1/metrics/dora (§7.8).

Metric values are null for an empty window; counts are 0, never null (§3).
"""

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.dora.bands import Band
from app.dora.queries import Bucket
from app.schemas.common import UtcDatetime
from app.schemas.deployments import Environment


class Window(BaseModel):
    # `from` is a Python keyword: the attribute is from_, the JSON key is "from".
    model_config = ConfigDict(validate_by_name=True, serialize_by_alias=True)

    from_: UtcDatetime = Field(alias="from")
    to: UtcDatetime
    days: float


class Filters(BaseModel):
    service_id: uuid.UUID | None
    environment: Environment


class DeploymentFrequency(BaseModel):
    count: int
    per_day: float | None
    deploy_days: int
    band: Band | None


class ChangeLeadTime(BaseModel):
    median_hours: float | None
    p90_hours: float | None
    sample_size: int
    excluded_samples: int
    band: Band | None


class ChangeFailRate(BaseModel):
    rate: float | None
    failed_deployments: int
    total_deployments: int
    band: Band | None


class RecoveryTime(BaseModel):
    median_hours: float | None
    sample_size: int
    open_failures: int
    band: Band | None


class ReworkRate(BaseModel):
    rate: float | None
    remediation_deployments: int
    total_deployments: int
    band: Band | None  # always null: DORA publishes no rework bands


class DoraSummary(BaseModel):
    window: Window
    filters: Filters
    band_set: str
    deployment_frequency: DeploymentFrequency
    change_lead_time: ChangeLeadTime
    change_fail_rate: ChangeFailRate
    failed_deployment_recovery_time: RecoveryTime
    deployment_rework_rate: ReworkRate


class TimeseriesPoint(BaseModel):
    start: UtcDatetime
    deployment_count: int
    median_lead_time_hours: float | None
    change_fail_rate: float | None
    median_recovery_hours: float | None
    rework_rate: float | None


class DoraTimeseries(BaseModel):
    window: Window
    filters: Filters
    bucket: Bucket
    points: list[TimeseriesPoint]
