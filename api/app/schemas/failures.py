import uuid
from typing import Annotated, ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, StringConstraints

from app.schemas.common import UtcDatetime
from app.schemas.patch import PatchModel

Severity = Literal["sev1", "sev2", "sev3", "sev4"]
Summary = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
ExternalRef = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class FailureCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deployment_id: uuid.UUID
    severity: Severity
    summary: Summary
    detected_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    external_ref: ExternalRef | None = None


class FailureUpdate(PatchModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"resolved_at", "external_ref"})

    deployment_id: uuid.UUID | None = None
    severity: Severity | None = None
    summary: Summary | None = None
    detected_at: AwareDatetime | None = None
    resolved_at: AwareDatetime | None = None
    external_ref: ExternalRef | None = None


class FailureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    deployment_id: uuid.UUID
    service_id: uuid.UUID
    severity: Severity
    summary: str
    detected_at: UtcDatetime
    resolved_at: UtcDatetime | None
    external_ref: str | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
