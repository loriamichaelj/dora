import uuid
from typing import Annotated, ClassVar, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.models.entities import SHA_PATTERN
from app.schemas.common import UtcDatetime
from app.schemas.failures import Severity
from app.schemas.patch import PatchModel
from app.services.transitions import Status

Environment = Literal["development", "staging", "production"]
Kind = Literal["planned", "remediation"]


def _lower(value: object) -> object:
    return value.lower() if isinstance(value, str) else value


# Git prints lowercase hex; accept either case and store lowercase.
Sha = Annotated[str, BeforeValidator(_lower), StringConstraints(pattern=SHA_PATTERN)]
Release = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Url = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]
ExternalId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
CommitMessage = Annotated[str, StringConstraints(max_length=1000)]

MAX_COMMITS = 500  # matches the self-tracking cap (§15.3)


class CommitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha: Sha
    committed_at: AwareDatetime
    author: ShortText | None = None
    message: CommitMessage | None = None


class DeploymentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    service_id: uuid.UUID
    environment: Environment
    kind: Kind = "planned"
    release: Release
    head_sha: Sha | None = None
    status: Status
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    deployed_by: ShortText | None = None
    pipeline_url: Url | None = None
    external_id: ExternalId | None = None
    commits: list[CommitIn] = Field(default_factory=list, max_length=MAX_COMMITS)


class DeploymentUpdate(PatchModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset(
        {"head_sha", "finished_at", "deployed_by", "pipeline_url"}
    )

    # Immutable after create (§6.3): accepted only if unchanged.
    service_id: uuid.UUID | None = None
    environment: Environment | None = None
    external_id: ExternalId | None = None

    kind: Kind | None = None
    release: Release | None = None
    head_sha: Sha | None = None
    status: Status | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    deployed_by: ShortText | None = None
    pipeline_url: Url | None = None
    # Additive: new commits are upserted and linked; existing links are kept.
    commits: list[CommitIn] | None = Field(default=None, max_length=MAX_COMMITS)


class CommitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sha: str
    committed_at: UtcDatetime
    author: str | None
    message: str | None


class FailureSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    severity: Severity
    summary: str
    detected_at: UtcDatetime
    resolved_at: UtcDatetime | None


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: uuid.UUID
    environment: Environment
    kind: Kind
    release: str
    head_sha: str | None
    status: Status
    started_at: UtcDatetime
    finished_at: UtcDatetime | None
    deployed_by: str | None
    pipeline_url: str | None
    external_id: str | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime


class DeploymentDetail(DeploymentOut):
    commits: list[CommitOut]
    failures: list[FailureSummary]
