import uuid
from typing import Annotated, ClassVar

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.models.entities import SLUG_PATTERN
from app.schemas.common import UtcDatetime
from app.schemas.patch import PatchModel

Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]
ServiceName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
OwnerTeam = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
RepoUrl = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)]


class ServiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    name: ServiceName
    owner_team: OwnerTeam
    repo_url: RepoUrl | None = None


class ServiceUpdate(PatchModel):
    nullable_fields: ClassVar[frozenset[str]] = frozenset({"repo_url"})

    slug: Slug | None = None  # immutable: accepted only if unchanged (§6.3)
    name: ServiceName | None = None
    owner_team: OwnerTeam | None = None
    repo_url: RepoUrl | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    owner_team: str
    repo_url: str | None
    version: int
    created_at: UtcDatetime
    updated_at: UtcDatetime
