import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Commit, deployment_commits


@dataclass(frozen=True)
class NewCommit:
    sha: str
    committed_at: datetime
    author: str | None
    message: str | None


@dataclass(frozen=True)
class StoredCommit:
    id: uuid.UUID
    sha: str
    committed_at: datetime


async def upsert(
    session: AsyncSession, service_id: uuid.UUID, commits: list[NewCommit]
) -> dict[str, StoredCommit]:
    """Insert commits that don't exist yet for this service; never overwrite
    an existing one (first write wins, §6.3). Returns every requested sha's
    stored row, so callers can detect a conflicting committed_at."""
    if not commits:
        return {}
    await session.execute(
        insert(Commit)
        .values(
            [
                {
                    "service_id": service_id,
                    "sha": c.sha,
                    "committed_at": c.committed_at,
                    "author": c.author,
                    "message": c.message,
                }
                for c in commits
            ]
        )
        .on_conflict_do_nothing(constraint="uq_service_sha")
    )
    rows = await session.execute(
        select(Commit.id, Commit.sha, Commit.committed_at).where(
            Commit.service_id == service_id, Commit.sha.in_([c.sha for c in commits])
        )
    )
    return {row.sha: StoredCommit(row.id, row.sha, row.committed_at) for row in rows}


async def link(session: AsyncSession, deployment_id: uuid.UUID, commit_ids: list[uuid.UUID]) -> int:
    """Link commits to a deployment. Returns how many links are new."""
    if not commit_ids:
        return 0
    result = await session.execute(
        insert(deployment_commits)
        .values([{"deployment_id": deployment_id, "commit_id": cid} for cid in commit_ids])
        .on_conflict_do_nothing()
        .returning(deployment_commits.c.commit_id)
    )
    return len(result.all())


async def for_deployment(session: AsyncSession, deployment_id: uuid.UUID) -> list[Commit]:
    stmt = (
        select(Commit)
        .join(deployment_commits, deployment_commits.c.commit_id == Commit.id)
        .where(deployment_commits.c.deployment_id == deployment_id)
        .order_by(Commit.committed_at.desc(), Commit.sha)
    )
    return list(await session.scalars(stmt))


# A commit is a *deployment commit* when at least one deployment ships it, and
# a *non-deployment commit* otherwise (for example, after the only deployment
# that shipped it was deleted). Derived from deployment_commits on every call,
# so the classification can never drift from the links.
_is_linked = exists().where(deployment_commits.c.commit_id == Commit.id)


@dataclass(frozen=True)
class CommitClassification:
    deployment_commits: int
    non_deployment_commits: int


async def classify_for_service(
    session: AsyncSession, service_id: uuid.UUID
) -> CommitClassification:
    row = (
        await session.execute(
            select(
                func.count().filter(_is_linked),
                func.count().filter(~_is_linked),
            ).where(Commit.service_id == service_id)
        )
    ).one()
    return CommitClassification(deployment_commits=row[0], non_deployment_commits=row[1])


async def delete_non_deployment_commits(session: AsyncSession, service_id: uuid.UUID) -> int:
    result = await session.execute(
        delete(Commit).where(Commit.service_id == service_id, ~_is_linked).returning(Commit.id)
    )
    return len(result.all())
