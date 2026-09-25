from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.schemas.deployments import (
    MAX_COMMITS,
    CommitIn,
    DeploymentDetail,
    Environment,
    ExternalId,
    Kind,
    Release,
    Sha,
    ShortText,
    Url,
)
from app.schemas.services import Slug
from app.services.transitions import Status


class DeploymentEvent(BaseModel):
    """A pipeline's report of a deployment's state (§7.6).

    Identified by (service_slug, external_id). The first event for a pair
    creates the deployment; later ones update it. Fields left out of a later
    event are left unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    service_slug: Slug
    external_id: ExternalId = Field(
        description="Idempotency key. For GitHub Actions: gha-<run_id>-<run_attempt>-<environment>"
    )
    environment: Environment
    kind: Kind = "planned"
    release: Release
    head_sha: Sha | None = None
    status: Status
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    deployed_by: ShortText | None = None
    pipeline_url: Url | None = None
    commits: list[CommitIn] = Field(default_factory=list, max_length=MAX_COMMITS)


class IngestResult(DeploymentDetail):
    ignored: Literal["stale_event"] | None = Field(
        default=None,
        description="Set when the event was older than the deployment's current state "
        "and was ignored. Not an error: retries and out-of-order delivery are normal.",
    )
