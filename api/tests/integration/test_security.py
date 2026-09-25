"""Least-privilege checks for the runtime role (§6.4, §12 "Security" row)."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.db import create_engine
from tests.integration.conftest import Database


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE dora.sneaky (id int)",
        "CREATE TABLE public.sneaky (id int)",
        "DROP TABLE dora.services",
        "ALTER TABLE dora.services ADD COLUMN sneaky int",
        "TRUNCATE dora.services",
        "CREATE SCHEMA sneaky",
    ],
)
async def test_app_role_cannot_run_ddl(migrated: Database, ddl: str) -> None:
    engine = create_engine(migrated.app, null_pool=True)
    try:
        async with engine.connect() as conn:
            with pytest.raises(ProgrammingError, match=r"permission denied|must be owner"):
                await conn.execute(text(ddl))
    finally:
        await engine.dispose()


async def test_app_role_has_dml_and_utc_session(migrated: Database) -> None:
    engine = create_engine(migrated.app, null_pool=True)
    try:
        async with engine.begin() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO services (slug, name, owner_team) "
                    "VALUES ('probe-svc', 'Probe', 'platform') RETURNING id"
                )
            )
            service_id = inserted.scalar_one()
            assert service_id.version == 7  # uuidv7()
            await conn.execute(
                text("UPDATE services SET name = 'Probe 2' WHERE id = :id"), {"id": service_id}
            )
            await conn.execute(text("DELETE FROM services WHERE id = :id"), {"id": service_id})
            assert (await conn.execute(text("SHOW timezone"))).scalar_one() == "UTC"
            assert (await conn.execute(text("SHOW search_path"))).scalar_one() == "dora"
    finally:
        await engine.dispose()
