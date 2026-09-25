"""Database connection.

Creates the async engine and provides sessions to the API layer.

Things to know when using Supabase (or any Postgres fronted by pgbouncer):

  - Port 5432 on `db.<ref>.supabase.co` is a DIRECT connection, IPv6 only.
    IPv4-only networks cannot reach it — use the connection pooler instead
    (`aws-<region>.pooler.supabase.com`).
  - The pooler in transaction mode does NOT support prepared statements, which
    asyncpg uses by default. They must be disabled with `statement_cache_size=0`,
    otherwise you get `DuplicatePreparedStatementError` under load.
  - Supabase requires SSL.

All of this is handled automatically in `connect_args_for()`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings, on_reload

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _is_pooled(url: str) -> bool:
    """Whether the connection goes through a pooler (pgbouncer)."""
    return "pooler.supabase.com" in url or ":6543" in url


def _needs_ssl(url: str) -> bool:
    """Servers on the internet require SSL; local ones do not."""
    return not any(host in url for host in ("localhost", "127.0.0.1", "@db:", "@postgres:"))


def connect_args_for(url: str) -> dict[str, Any]:
    args: dict[str, Any] = {}

    if _needs_ssl(url):
        args["ssl"] = "require"

    if _is_pooled(url):
        # pgbouncer in transaction mode cannot use prepared statements.
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0

    return args


def create_engine() -> AsyncEngine:
    """Build the engine from the current configuration."""
    config = get_settings()
    url = config.DATABASE_URL

    if url.startswith("postgresql://"):
        raise ValueError(
            "DATABASE_URL must use an async driver. "
            "Change 'postgresql://' to 'postgresql+asyncpg://' in .env."
        )

    pooled = _is_pooled(url)
    return create_async_engine(
        url,
        # NOT `echo=True`: echo attaches SQLAlchemy's own handler to the
        # `sqlalchemy.engine` logger, and the same record also reaches the root
        # handler — every statement printed twice. SQL logging is switched on
        # by level instead, in app/core/logging.py.
        echo=False,
        # pool_pre_ping sends a "SELECT 1" before EVERY connection checkout.
        # With a database in the same region that is negligible, but here each
        # round trip costs 0.6-1 seconds, so it nearly doubles the time of the
        # light endpoints. Instead, retire connections by age: `pool_recycle` is
        # much shorter than the time after which pgbouncer drops idle connections.
        pool_pre_ping=not pooled,
        pool_recycle=300 if pooled else 1800,
        # Behind a pooler, keep the app-side pool SMALL, but not a single
        # connection: opening one chat page already fires several API calls in
        # parallel, and each query to Supabase takes a few hundred milliseconds.
        # With a pool of 1 the queries queue behind each other and the page
        # takes 3-6 seconds to appear — users think their click did nothing.
        pool_size=5,
        max_overflow=10 if not pooled else 5,
        connect_args=connect_args_for(url),
    )


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_engine()
        _sessionmaker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Commits when done, rolls back on error.

        @router.get("/threads")
        async def list_threads(db: AsyncSession = Depends(get_session)): ...
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> dict[str, Any]:
    """Try connecting to the database. Used at startup and by the health endpoint."""
    try:
        async with get_engine().connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            database = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        return {"ok": True, "server_version": version, "database": database}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def dispose_engine() -> None:
    """Close every connection. Called on application shutdown."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@on_reload
def _reset_on_config_change() -> None:
    """Rebuild the engine only when DATABASE_URL itself changed.

    This runs on EVERY configuration change — saving LLM_TEMPERATURE on the
    Settings page included. Dropping the engine each time threw away a warm
    connection pool and paid the 0.6-1 s round trip to lab1 again on the next
    query, for a setting that has nothing to do with the database. DATABASE_URL
    can only change through "Reload .env", so compare before discarding.

    Only drop the reference — we cannot close it here because this function
    runs synchronously. The old connections will be closed by the garbage
    collector.
    """
    global _engine, _sessionmaker
    if _engine is None:
        return
    if _engine.url.render_as_string(hide_password=False) == get_settings().DATABASE_URL:
        return
    logger.info("DATABASE_URL changed; the database connection will be rebuilt on next use")
    _engine = None
    _sessionmaker = None


__all__ = [
    "check_connection",
    "connect_args_for",
    "create_engine",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
