"""Alembic migration environment.

Differences from the template Alembic generates:

  - The URL comes from `app.core.config`, not from alembic.ini — so the
    password lives only in .env and never ends up in a committed file.
  - ALEMBIC_DATABASE_URL takes precedence if set. Migrations need a Postgres
    advisory lock so two people do not run over each other, and a connection
    pooler in transaction mode cannot hold that lock across statements.
  - Uses an async engine because the whole project runs on asyncpg; no extra
    sync driver is installed just for migrations.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import connect_args_for

# Imported so every table is present in Base.metadata before comparing.
import app.db.models  # noqa: F401  (required, see app/db/models/__init__.py)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    settings = get_settings()
    return settings.ALEMBIC_DATABASE_URL or settings.DATABASE_URL


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Without these two lines, column type changes and default value
        # changes are not detected by autogenerate.
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Only print the SQL statements, without connecting. `alembic upgrade --sql`."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = database_url()
    engine = async_engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        # A migration runs once and exits; no need to keep a pool.
        poolclass=pool.NullPool,
        connect_args=connect_args_for(url),
    )

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
