"""Persistence and orchestration for the Tools tab.

The registry (app/modules/tools/registry.py) holds the live state in memory;
this service writes it to Postgres and reloads it at startup, connects MCP
servers, and runs tools on behalf of a user with a history row per run.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.db.models.tool import McpServer, McpTool, ToolRun, ToolSetting
from app.db.models.user import User
from app.modules.tools import mcp_client
from app.modules.tools.registry import McpToolRecord, registry
from app.modules.tools.schema import Danger, ToolSpec

logger = logging.getLogger(__name__)

SERVER_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
MAX_STORED_OUTPUT = 20_000


class ToolServiceError(ValueError):
    """Rejected request. Message is user-facing."""


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------


def _token(server: McpServer) -> str | None:
    if not server.token_enc:
        return None
    try:
        return decrypt_secret(server.token_enc)
    except InvalidToken:
        logger.warning(
            "Could not decrypt the token of MCP server %s (JWT_SECRET changed?)", server.name
        )
        return None


def _records(server: McpServer, tools: Sequence[McpTool]) -> list[McpToolRecord]:
    token = _token(server)
    return [
        McpToolRecord(
            server_name=server.name,
            server_url=server.url,
            token=token,
            tool=t.name,
            description=t.description,
            input_schema=t.input_schema,
            read_only_hint=t.read_only_hint,
        )
        for t in tools
    ]


async def load_into_registry(db: AsyncSession) -> None:
    """Called once from the lifespan: tool state + cached MCP tools."""
    rows = (await db.execute(select(ToolSetting))).scalars().all()
    registry.load_state([(r.name, r.enabled, r.danger) for r in rows])
    servers = (
        (await db.execute(select(McpServer).where(McpServer.enabled.is_(True)))).scalars().all()
    )
    for server in servers:
        tools = (
            (await db.execute(select(McpTool).where(McpTool.server_id == server.id)))
            .scalars()
            .all()
        )
        registry.set_mcp_tools(server.name, _records(server, tools))


# --------------------------------------------------------------------------
# Catalog state
# --------------------------------------------------------------------------


async def update_tool(
    db: AsyncSession, spec: ToolSpec, *, actor: User, enabled: bool | None, danger: Danger | None
) -> None:
    if danger is not None and registry.is_builtin(spec.name):
        raise ToolServiceError(
            "The danger level of a built-in tool is fixed in code and can't be changed."
        )
    row = await db.get(ToolSetting, spec.name)
    if row is None:
        row = ToolSetting(name=spec.name, enabled=registry.is_enabled(spec))
        db.add(row)
    if enabled is not None:
        row.enabled = enabled
    if danger is not None:
        row.danger = danger.value
    row.updated_by = actor.id
    await db.flush()
    registry.set_state(spec.name, enabled=enabled, danger=danger)


# --------------------------------------------------------------------------
# MCP servers
# --------------------------------------------------------------------------


def _check_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ToolServiceError(
            "The URL must start with http:// or https://, e.g. http://host:8000/mcp"
        )
    return url.strip()


async def list_servers(db: AsyncSession) -> list[tuple[McpServer, int]]:
    stmt = (
        select(McpServer, func.count(McpTool.name))
        .outerjoin(McpTool, McpTool.server_id == McpServer.id)
        .group_by(McpServer.id)
        .order_by(McpServer.created_at)
    )
    return [(s, int(n)) for s, n in (await db.execute(stmt)).all()]


async def refresh_server(db: AsyncSession, server: McpServer, *, _mcp_server: Any = None) -> None:
    """Ask the server for its tools and replace the cached list. Never raises for
    a server problem: the error is stored and shown on the page instead."""
    try:
        tools = await mcp_client.list_tools(server.url, _token(server), _server=_mcp_server)
    except mcp_client.McpError as exc:
        server.last_error = str(exc)
        server.refreshed_at = datetime.now(UTC)
        await db.flush()
        return

    await db.execute(delete(McpTool).where(McpTool.server_id == server.id))
    rows = [
        McpTool(
            server_id=server.id,
            name=t.name,
            description=t.description,
            input_schema=t.input_schema,
            read_only_hint=t.read_only_hint,
        )
        for t in tools
    ]
    db.add_all(rows)
    server.last_error = None
    server.refreshed_at = datetime.now(UTC)
    await db.flush()
    if server.enabled:
        registry.set_mcp_tools(server.name, _records(server, rows))


async def add_server(
    db: AsyncSession, *, name: str, url: str, token: str | None, _mcp_server: Any = None
) -> McpServer:
    if not SERVER_NAME.match(name):
        raise ToolServiceError(
            "Use 2–32 characters: lowercase letters, digits and '-', starting with a letter."
        )
    existing = await db.execute(select(McpServer).where(McpServer.name == name))
    if existing.scalar_one_or_none() is not None:
        raise ToolServiceError(f"A server named {name!r} already exists.")
    server = McpServer(
        name=name,
        url=_check_url(url),
        enabled=True,
        token_enc=encrypt_secret(token) if token else None,
    )
    db.add(server)
    await db.flush()
    await refresh_server(db, server, _mcp_server=_mcp_server)
    return server


async def set_server_enabled(db: AsyncSession, server: McpServer, enabled: bool) -> None:
    server.enabled = enabled
    await db.flush()
    if enabled:
        tools = (
            (await db.execute(select(McpTool).where(McpTool.server_id == server.id)))
            .scalars()
            .all()
        )
        registry.set_mcp_tools(server.name, _records(server, tools))
    else:
        registry.remove_mcp_server(server.name)


async def delete_server(db: AsyncSession, server: McpServer) -> None:
    """Removes the connection and its cached tools. Past run history is kept."""
    await db.delete(server)
    await db.flush()
    registry.remove_mcp_server(server.name)


# --------------------------------------------------------------------------
# Running a tool from the Tools tab
# --------------------------------------------------------------------------


async def run_tool(
    db: AsyncSession, spec: ToolSpec, *, actor: User, args: dict[str, Any]
) -> ToolRun:
    reason = registry.can_run(spec)
    if reason:
        raise ToolServiceError(reason)

    started = time.perf_counter()
    try:
        output = await spec.tool.ainvoke(args)
        ok = True
        text = str(output)
    except Exception as exc:  # validation errors from the args schema, mostly
        ok = False
        text = f"{type(exc).__name__}: {exc}"
    run = ToolRun(
        id=uuid.uuid4(),
        tool=spec.name,
        actor_id=actor.id,
        actor_email=actor.email,
        args=jsonable_encoder(args),
        ok=ok,
        output=text[:MAX_STORED_OUTPUT],
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
    db.add(run)
    await db.flush()
    return run


async def list_runs(
    db: AsyncSession, *, tool: str | None, limit: int, offset: int
) -> tuple[Sequence[ToolRun], int]:
    base = select(ToolRun)
    count = select(func.count()).select_from(ToolRun)
    if tool:
        base = base.where(ToolRun.tool == tool)
        count = count.where(ToolRun.tool == tool)
    total = int((await db.execute(count)).scalar_one())
    rows = (
        (await db.execute(base.order_by(ToolRun.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return rows, total


__all__ = [
    "ToolServiceError",
    "add_server",
    "delete_server",
    "list_runs",
    "list_servers",
    "load_into_registry",
    "refresh_server",
    "run_tool",
    "set_server_enabled",
    "update_tool",
]
