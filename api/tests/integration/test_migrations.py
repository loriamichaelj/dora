"""Migration and bootstrap checks (§12 "Migrations" row, §16)."""

from collections.abc import Iterator

import pytest
from sqlalchemy import text

from app.db import create_engine
from tests.integration.conftest import Database, database_for, run_alembic, start_postgres

# Everything a second bootstrap run could change: roles (including password
# hashes), memberships, schema ownership and ACLs, and default privileges.
CATALOG_SNAPSHOT = """
SELECT a.rolname, a.rolpassword, a.rolcanlogin, a.rolsuper, s.setconfig
  FROM pg_authid a LEFT JOIN pg_db_role_setting s ON s.setrole = a.oid
 WHERE a.rolname LIKE 'dora%' ORDER BY a.rolname;
SELECT roleid::regrole, member::regrole, inherit_option, set_option, admin_option
  FROM pg_auth_members WHERE roleid::regrole::text LIKE 'dora%' ORDER BY 1, 2;
SELECT nspname, nspowner::regrole, nspacl FROM pg_namespace WHERE nspname = 'dora';
SELECT defaclrole::regrole, defaclnamespace::regnamespace, defaclobjtype, defaclacl
  FROM pg_default_acl ORDER BY 1, 2, 3;
"""

DORA_TABLES = {
    "alembic_version",
    "services",
    "deployments",
    "commits",
    "deployment_commits",
    "failures",
}


async def table_names(database: Database) -> set[str]:
    engine = create_engine(database.owner, null_pool=True)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'dora'")
            )
            return {row[0] for row in rows}
    finally:
        await engine.dispose()


async def test_upgrade_downgrade_upgrade_round_trip(scratch_database: Database) -> None:
    db = scratch_database
    await run_alembic(db.owner, "upgrade", "head")
    assert await table_names(db) == DORA_TABLES

    await run_alembic(db.owner, "downgrade", "base")
    assert await table_names(db) == {"alembic_version"}
    default_acl = db.psql("-At", "-c", "SELECT count(*) FROM pg_default_acl")
    assert default_acl.strip() == "0"

    await run_alembic(db.owner, "upgrade", "head")
    assert await table_names(db) == DORA_TABLES


async def test_models_match_migrations(migrated: Database) -> None:
    # `alembic check` raises if autogenerate would emit any operation.
    await run_alembic(migrated.owner, "check")


def test_bootstrap_twice_is_a_no_op(database: Database) -> None:
    before = database.psql("-At", "-c", CATALOG_SNAPSHOT)
    database.bootstrap()
    after = database.psql("-At", "-c", CATALOG_SNAPSHOT)
    assert after == before


@pytest.fixture
def rds_like_database() -> Iterator[Database]:
    """A fresh cluster where bootstrap runs as a CREATEROLE, non-superuser
    database owner, like the Amazon RDS master user."""
    container = start_postgres()
    try:
        db = database_for(container)
        db.psql("-c", "CREATE ROLE rds_master LOGIN CREATEROLE")
        db.psql("-c", "ALTER DATABASE dora OWNER TO rds_master")
        yield db
    finally:
        container.stop()


def test_bootstrap_works_without_superuser(rds_like_database: Database) -> None:
    rds_like_database.bootstrap(user="rds_master")
    before = rds_like_database.psql("-At", "-c", CATALOG_SNAPSHOT)
    rds_like_database.bootstrap(user="rds_master")
    after = rds_like_database.psql("-At", "-c", CATALOG_SNAPSHOT)
    assert after == before

    owner = rds_like_database.psql(
        "-At", "-c", "SELECT nspowner::regrole FROM pg_namespace WHERE nspname = 'dora'"
    )
    assert owner.strip() == "dora_owner"
