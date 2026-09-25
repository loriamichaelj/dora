"""Alembic environment: async engine built from the DB_* environment variables.

Runs only in the one-shot migrate process (D2), as dora_owner. Callers such as
the test suite may pass a ready connection through `config.attributes`; it must
come from `create_migration_engine` (see its docstring).
"""

import asyncio
import logging
from logging.config import fileConfig

from sqlalchemy.engine import Connection

from alembic import context
from app.config import get_database_settings
from app.db import create_migration_engine
from app.models import SCHEMA, Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

log = logging.getLogger("alembic.env")
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # Autogenerate and `alembic check` only look at the app's schema.
    if type_ == "schema":
        return name == SCHEMA
    return True


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_migration_engine(get_database_settings())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
    else:
        asyncio.run(run_async_migrations())


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) migrations are not supported; run against a database.")
run_migrations_online()
