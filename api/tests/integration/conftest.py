"""Integration fixtures: a real PostgreSQL 18 via Testcontainers (never SQLite, D8).

One container per test session. It is bootstrapped with db/bootstrap.sql
exactly as the local stack and RDS are, then migrated to head as dora_owner.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy.engine import Connection
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.config import DatabaseSettings
from app.db import create_migration_engine

API_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = API_DIR.parent
BOOTSTRAP_SQL = REPO_DIR / "db" / "bootstrap.sql"
POSTGRES_IMAGE = "postgres:18.6"

OWNER_PASSWORD = "owner-test-password"
APP_PASSWORD = "app-test-password"


@dataclass(frozen=True)
class Database:
    container: PostgresContainer
    host: str
    port: int

    def settings(self, user: str, password: str) -> DatabaseSettings:
        return DatabaseSettings(
            db_host=self.host,
            db_port=self.port,
            db_name="dora",
            db_user=user,
            db_password=password,
            db_ssl_mode="disable",
        )

    @property
    def owner(self) -> DatabaseSettings:
        return self.settings("dora_owner", OWNER_PASSWORD)

    @property
    def app(self) -> DatabaseSettings:
        return self.settings("dora_app", APP_PASSWORD)

    def psql(self, *args: str, user: str = "postgres") -> str:
        """Run psql inside the container over the local socket (trust auth)."""
        result = self.container.exec(
            ["psql", "--no-psqlrc", "-v", "ON_ERROR_STOP=1", "-U", user, "-d", "dora", *args]
        )
        output = result.output.decode()
        if result.exit_code != 0:
            raise AssertionError(f"psql failed ({result.exit_code}):\n{output}")
        return output

    def bootstrap(self, user: str = "postgres") -> str:
        return self.psql(
            "-v",
            f"owner_password={OWNER_PASSWORD}",
            "-v",
            f"app_password={APP_PASSWORD}",
            "-f",
            "/bootstrap.sql",
            user=user,
        )


def start_postgres() -> PostgresContainer:
    container = PostgresContainer(
        POSTGRES_IMAGE, username="postgres", password="postgres", dbname="dora", driver=None
    ).with_volume_mapping(str(BOOTSTRAP_SQL), "/bootstrap.sql", mode="ro")
    container.start()
    return container


def database_for(container: PostgresContainer) -> Database:
    return Database(
        container=container,
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
    )


def alembic_config() -> Config:
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    config.attributes["configure_logging"] = False
    return config


async def run_alembic(settings: DatabaseSettings, action: str, revision: str = "head") -> None:
    """Run an Alembic command on a connection we own (upgrade/downgrade/check)."""
    config = alembic_config()

    def _run(connection: Connection) -> None:
        config.attributes["connection"] = connection
        if action == "upgrade":
            command.upgrade(config, revision)
        elif action == "downgrade":
            command.downgrade(config, revision)
        elif action == "check":
            command.check(config)
        else:
            raise ValueError(action)

    engine = create_migration_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    container = start_postgres()
    try:
        db = database_for(container)
        db.bootstrap()
        yield db
    finally:
        container.stop()


@pytest.fixture(scope="session")
async def migrated(database: Database) -> Database:
    await run_alembic(database.owner, "upgrade")
    return database
