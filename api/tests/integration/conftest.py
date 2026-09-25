"""Integration fixtures: a real PostgreSQL 18 via Testcontainers (never SQLite, D8).

One container per test session. It is bootstrapped with db/bootstrap.sql
exactly as the local stack and RDS are, then migrated to head as dora_owner.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from app.config import DatabaseSettings
from app.db import create_engine, create_migration_engine
from app.main import create_app

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


@contextmanager
def bootstrapped_postgres() -> Iterator[Database]:
    container = start_postgres()
    try:
        db = database_for(container)
        db.bootstrap()
        yield db
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database() -> Iterator[Database]:
    """The shared test database. Tests may add and delete rows, never change schema."""
    with bootstrapped_postgres() as db:
        yield db


@pytest.fixture
def scratch_database() -> Iterator[Database]:
    """A private, bootstrapped database for tests that change the schema."""
    with bootstrapped_postgres() as db:
        yield db


@pytest.fixture(scope="session")
async def migrated(database: Database) -> Database:
    await run_alembic(database.owner, "upgrade")
    return database


DATA_TABLES = ", ".join(
    f"dora.{t}" for t in ("failures", "deployment_commits", "commits", "deployments", "services")
)


@pytest.fixture(scope="session")
async def owner_engine(migrated: Database) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(migrated.owner, null_pool=True)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(migrated: Database) -> AsyncIterator[AsyncEngine]:
    """Runs as dora_app, like the API. For arranging rows the API can't create yet."""
    engine = create_engine(migrated.app, null_pool=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def clean_tables(owner_engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {DATA_TABLES}"))


@pytest.fixture(scope="session")
async def api_app(migrated: Database) -> AsyncIterator[FastAPI]:
    app = create_app(db_settings=migrated.app)
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def api(api_app: FastAPI, clean_tables: None) -> AsyncIterator[AsyncClient]:
    """HTTP client for the API against the shared database; rows are wiped after each test."""
    transport = ASGITransport(app=api_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
