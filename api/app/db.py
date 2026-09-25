"""Database engine and session plumbing.

Every connection runs with timezone=UTC (§3, §7.8), survives restarts and
failovers (pre-ping, recycle), and maps DB_SSL_MODE onto asyncpg's `ssl`
argument, because asyncpg ignores libpq's `sslmode` in a SQLAlchemy URL.
"""

import ssl
from typing import Any

from sqlalchemy import URL
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.config import DatabaseSettings

CONNECT_TIMEOUT_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 30


def database_url(settings: DatabaseSettings) -> URL:
    return URL.create(
        "postgresql+asyncpg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value() or None,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


def ssl_argument(settings: DatabaseSettings) -> ssl.SSLContext | bool:
    """Translate DB_SSL_MODE into the value asyncpg expects for `ssl`."""
    if settings.db_ssl_mode == "disable":
        return False
    if settings.db_ssl_mode == "require":
        # Encrypt, but don't verify the server certificate (libpq semantics).
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    return ssl.create_default_context(cafile=settings.db_ssl_root_cert or None)


def connect_args(settings: DatabaseSettings, search_path: str | None = None) -> dict[str, Any]:
    server_settings = {"timezone": "UTC", "application_name": "dora-api"}
    if search_path is not None:
        server_settings["search_path"] = search_path
    return {
        "ssl": ssl_argument(settings),
        "server_settings": server_settings,
        # asyncpg waits 60s to connect by default and forever on a statement;
        # bound both so a DB outage or network partition becomes a 503, not a hang.
        "timeout": CONNECT_TIMEOUT_SECONDS,
        "command_timeout": COMMAND_TIMEOUT_SECONDS,
    }


def create_engine(
    settings: DatabaseSettings, *, null_pool: bool = False, search_path: str | None = None
) -> AsyncEngine:
    """Build the async engine. One-shot processes (migrate, seed) pass
    null_pool=True so no connections outlive their work."""
    options: dict[str, Any] = {"connect_args": connect_args(settings, search_path)}
    if null_pool:
        options["poolclass"] = NullPool
    else:
        options.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
        )
    return create_async_engine(database_url(settings), **options)


def create_migration_engine(settings: DatabaseSettings) -> AsyncEngine:
    """Engine for Alembic. The owner role's default search_path is `dora`, which
    would make reflection report the app's tables as unqualified. Pinning the
    search_path to pg_catalog *at connect time* (before SQLAlchemy caches the
    default schema) makes them reflect as `dora.<table>`, matching the
    schema-qualified metadata, and forces migrations to qualify every name."""
    return create_engine(settings, null_pool=True, search_path="pg_catalog")


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
