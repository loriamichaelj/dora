import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Deployment


async def get(session: AsyncSession, deployment_id: uuid.UUID) -> Deployment | None:
    return await session.scalar(select(Deployment).where(Deployment.id == deployment_id))
