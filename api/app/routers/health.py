"""Operational endpoints served at the root, outside /api/v1 (§7.2)."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import get_settings

router = APIRouter(tags=["operational"])


class LivenessResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    version: str
    git_sha: str
    build_time: str


@router.get("/healthz", response_model=LivenessResponse)
async def healthz() -> LivenessResponse:
    """Liveness only: never touches the database (D1)."""
    return LivenessResponse(status="ok")


@router.get("/version", response_model=VersionResponse)
async def version() -> VersionResponse:
    settings = get_settings()
    return VersionResponse(
        version=settings.app_version,
        git_sha=settings.git_sha,
        build_time=settings.build_time,
    )
