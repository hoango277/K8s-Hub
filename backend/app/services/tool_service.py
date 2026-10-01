"""Persistence and orchestration for the Tools tab.

The registry (app/modules/tools/registry.py) holds the live state in memory;
this service writes it to Postgres and reloads it at startup, manages custom
tools and external MCP servers (with each MCP tool's policy), and runs tools on
behalf of a user with a history row per run.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import InvalidToken, decrypt_secret, encrypt_secret
from app.db.models.message import Message, ToolCall
from app.db.models.thread import ChatThread
from app.db.models.tool import CustomTool, McpServer, McpTool, ToolRun, ToolSetting
from app.db.models.user import User
from app.db.session import get_sessionmaker
from app.modules.tools import mcp_client
from app.modules.tools.custom import COMMAND, NAME, CustomToolDef
from app.modules.tools.mcp import McpToolRecord, mcp_tool_name
from app.modules.tools.registry import registry
from app.modules.tools.schema import ToolSpec

logger = logging.getLogger(__name__)

MAX_STORED_OUTPUT = 20_000
SERVER_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
MAX_PREFIXES = 30
_PREFIX = re.compile(r"^[A-Za-z0-9:._-]+( [A-Za-z0-9:._-]+){0,3}$")
# Names the chat already uses for tools that don't live in the registry.
_RESERVED = frozenset(
    {"system_info", "current_time", "load_skill", "read_skill_file", "run_skill_script"}
)


class ToolServiceError(ValueError):
    """Rejected request. Message is user-facing."""


def _def(row: CustomTool) -> CustomToolDef:
    return CustomToolDef(
        name=row.name,
        title=row.title,
        description=row.description,
        command=row.command,
        usage=row.usage,
        read_only_prefixes=list(row.read_only_prefixes or []),
        timeout_seconds=row.timeout_seconds,
        enabled=row.enabled,
    )


def _records(server: McpServer, tools: Sequence[McpTool]) -> list[McpToolRecord]:
    return [
        McpToolRecord(
            server_id=str(server.id),
            server_name=server.name,
            server_url=server.url,
            tool=t.name,
            description=t.description,
            input_schema=t.input_schema,
            read_only_hint=t.read_only_hint,
            enabled=t.enabled,
            requires_approval=t.requires_approval,
        )
        for t in tools
    ]


async def _server_tools(db: AsyncSession, server: McpServer) -> Sequence[McpTool]:
    stmt = select(McpTool).where(McpTool.server_id == server.id).order_by(McpTool.name)
    return (await db.execute(stmt)).scalars().all()


async def load_into_registry(db: AsyncSession) -> None:
    """Called once from the lifespan: built-in tool state, custom tools, MCP tools."""
    rows = (await db.execute(select(ToolSetting))).scalars().all()
    registry.load_state([(r.name, r.enabled) for r in rows])
    custom = (await db.execute(select(CustomTool).order_by(CustomTool.name))).scalars().all()
    registry.set_custom_tools([_def(r) for r in custom])
    servers = (
        (await db.execute(select(McpServer).where(McpServer.enabled.is_(True)))).scalars().all()
    )
    for server in servers:
        registry.set_mcp_tools(server.name, _records(server, await _server_tools(db, server)))


# --------------------------------------------------------------------------
# Enable / disable
# --------------------------------------------------------------------------


async def set_enabled(db: AsyncSession, spec: ToolSpec, *, actor: User, enabled: bool) -> None:
    if registry.mcp_record(spec.name) is not None:
        await set_mcp_policy(db, spec.name, actor=actor, enabled=enabled)
        return
    custom = await db.get(CustomTool, spec.name)
    if custom is not None:
        custom.enabled = enabled
    else:
        row = await db.get(ToolSetting, spec.name)
        if row is None:
            row = ToolSetting(name=spec.name, enabled=enabled)
            db.add(row)
        row.enabled = enabled
        row.updated_by = actor.id
    await db.flush()
    registry.set_enabled(spec.name, enabled)


# --------------------------------------------------------------------------
# Custom tools
# --------------------------------------------------------------------------


def _check(d: CustomToolDef, *, creating: bool) -> CustomToolDef:
    if creating:
        if not NAME.match(d.name):
            raise ToolServiceError(
                "Name: 2–40 characters, lowercase letters, digits and '_', starting with a letter."
            )
        if d.name in _RESERVED or registry.is_builtin(d.name):
            raise ToolServiceError(f"{d.name!r} is already the name of a built-in tool.")
    if not COMMAND.match(d.command):
        raise ToolServiceError(
            "Command: the program name only (e.g. kubectl, helm) — no path, no arguments."
        )
    prefixes = [" ".join(p.split()) for p in d.read_only_prefixes if p.strip()]
    if len(prefixes) > MAX_PREFIXES:
        raise ToolServiceError(f"At most {MAX_PREFIXES} read-only subcommands.")
    bad = [p for p in prefixes if not _PREFIX.match(p)]
    if bad:
        raise ToolServiceError(
            f"Read-only subcommands are 1–4 plain words each, e.g. 'get' or 'rollout status'. "
            f"Invalid: {', '.join(bad)}"
        )
    if not 5 <= d.timeout_seconds <= 300:
        raise ToolServiceError("The time limit must be between 5 and 300 seconds.")
    d.read_only_prefixes = list(dict.fromkeys(prefixes))
    return d


async def list_custom(db: AsyncSession) -> Sequence[CustomTool]:
    return (await db.execute(select(CustomTool).order_by(CustomTool.name))).scalars().all()


async def create_custom(db: AsyncSession, d: CustomToolDef, *, actor: User) -> CustomTool:
    _check(d, creating=True)
    if await db.get(CustomTool, d.name) is not None:
        raise ToolServiceError(f"A custom tool named {d.name!r} already exists.")
    row = CustomTool(
        name=d.name,
        title=d.title,
        description=d.description,
        command=d.command,
        usage=d.usage,
        read_only_prefixes=d.read_only_prefixes,
        timeout_seconds=d.timeout_seconds,
        enabled=d.enabled,
        created_by=actor.id,
    )
    db.add(row)
    await db.flush()
    registry.upsert_custom(_def(row))
    return row


async def update_custom(db: AsyncSession, row: CustomTool, d: CustomToolDef) -> CustomTool:
    d.name = row.name  # the name is the model's handle for it: fixed once created
    _check(d, creating=False)
    row.title = d.title
    row.description = d.description
    row.command = d.command
    row.usage = d.usage
    row.read_only_prefixes = d.read_only_prefixes
    row.timeout_seconds = d.timeout_seconds
    row.enabled = d.enabled
    await db.flush()
    registry.upsert_custom(_def(row))
    return row


async def delete_custom(db: AsyncSession, row: CustomTool) -> None:
    """The definition goes; its run history and approvals stay (audit)."""
    name = row.name
    await db.delete(row)
    await db.flush()
    registry.remove_custom(name)


# --------------------------------------------------------------------------
# MCP servers and the policy of their tools
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


async def server_token(server_id: str) -> str | None:
    """The bearer token, read when a call runs (never stored in a plan or a record).
    Raises LookupError when the server was removed since."""
    async with get_sessionmaker()() as db:
        server = await db.get(McpServer, uuid.UUID(str(server_id)))
        if server is None:
            raise LookupError("This MCP server was removed; the call can't run.")
        return _token(server)


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
    """Ask the server for its tools. Tools seen before keep their policy; new
    ones arrive disabled and requiring approval; vanished ones are dropped.
    Never raises for a server problem: the error is stored and shown instead."""
    try:
        remote = await mcp_client.list_tools(server.url, _token(server), _server=_mcp_server)
    except mcp_client.McpError as exc:
        server.last_error = str(exc)
        server.refreshed_at = datetime.now(UTC)
        await db.flush()
        return

    known = {t.name: t for t in await _server_tools(db, server)}
    await db.execute(delete(McpTool).where(McpTool.server_id == server.id))
    rows = []
    for t in remote:
        old = known.get(t.name)
        rows.append(
            McpTool(
                server_id=server.id,
                name=t.name,
                description=t.description,
                input_schema=t.input_schema,
                read_only_hint=t.read_only_hint,
                enabled=old.enabled if old else False,
                requires_approval=old.requires_approval if old else True,
                policy_updated_by=old.policy_updated_by if old else None,
                policy_updated_at=old.policy_updated_at if old else None,
            )
        )
    db.add_all(rows)
    server.last_error = None
    server.refreshed_at = datetime.now(UTC)
    await db.flush()
    if server.enabled:
        registry.set_mcp_tools(server.name, _records(server, rows))


async def add_server(
    db: AsyncSession,
    *,
    actor: User,
    name: str,
    url: str,
    token: str | None,
    _mcp_server: Any = None,
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
        created_by=actor.id,
    )
    db.add(server)
    await db.flush()
    await refresh_server(db, server, _mcp_server=_mcp_server)
    return server


async def set_server_enabled(db: AsyncSession, server: McpServer, enabled: bool) -> None:
    server.enabled = enabled
    await db.flush()
    if enabled:
        registry.set_mcp_tools(server.name, _records(server, await _server_tools(db, server)))
    else:
        registry.remove_mcp_server(server.name)


async def delete_server(db: AsyncSession, server: McpServer) -> None:
    """Removes the connection, its tools and their policies. Past runs and
    approvals stay (audit); a pending approval for it can no longer run."""
    await db.delete(server)
    await db.flush()
    registry.remove_mcp_server(server.name)


async def set_mcp_policy(
    db: AsyncSession,
    name: str,
    *,
    actor: User,
    enabled: bool | None = None,
    requires_approval: bool | None = None,
) -> None:
    rec = registry.mcp_record(name)
    if rec is None:
        raise ToolServiceError(f"{name!r} is not an MCP tool.")
    row = await db.get(McpTool, (uuid.UUID(rec.server_id), rec.tool))
    if row is None:
        raise ToolServiceError(f"{name!r} is no longer reported by its server; refresh it.")
    if enabled is not None:
        row.enabled = enabled
    if requires_approval is not None:
        row.requires_approval = requires_approval
    row.policy_updated_by = actor.id
    row.policy_updated_at = datetime.now(UTC)
    await db.flush()
    registry.set_mcp_policy(name, enabled=enabled, requires_approval=requires_approval)
    logger.info(
        "MCP tool policy changed by %s: %s enabled=%s requires_approval=%s",
        actor.email,
        name,
        row.enabled,
        row.requires_approval,
    )


# --------------------------------------------------------------------------
# Running a tool from the Tools tab
# --------------------------------------------------------------------------


async def run_tool(
    db: AsyncSession, spec: ToolSpec, *, actor: User, args: dict[str, Any]
) -> ToolRun:
    reason = registry.can_run(spec)
    if reason:
        raise ToolServiceError(reason)

    # The same metadata a chat turn carries: write tools read it to know who
    # is proposing (approval_service.actor_from_config).
    config = {"metadata": {"user_id": str(actor.id), "user": actor.email, "user_role": actor.role}}
    started = time.perf_counter()
    try:
        output = await spec.tool.ainvoke(args, config=config)
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


@dataclass
class RunEntry:
    """One tool run for the history, whichever way it was started."""

    id: uuid.UUID
    tool: str
    trigger: str  # "manual" (Tools tab) or "chat"
    actor_email: str
    args: dict[str, Any]
    ok: bool
    output: str
    duration_ms: int
    created_at: datetime
    thread_id: uuid.UUID | None = None


async def list_runs(
    db: AsyncSession,
    *,
    tool: str | None,
    limit: int,
    offset: int,
    actor_id: uuid.UUID | None = None,
) -> tuple[list[RunEntry], int]:
    """Manual runs (`tool_runs`) and the assistant's tool calls (`tool_calls`),
    newest first, paged as ONE list.

    Paging is done on the merged order: the newest `offset + limit` of each
    source are enough to know the rows `offset .. offset + limit` of the
    union, so "Show more" never reshuffles rows already shown.
    `actor_id` limits both sources to one user (a plain user's view).
    """
    window = offset + limit

    manual = select(ToolRun)
    manual_count = select(func.count()).select_from(ToolRun)
    chat = (
        select(ToolCall, User.email, ChatThread.id)
        .join(Message, ToolCall.message_id == Message.id)
        .join(ChatThread, Message.thread_id == ChatThread.id)
        .join(User, ChatThread.user_id == User.id)
        .where(ToolCall.status != "running")
    )
    chat_count = (
        select(func.count())
        .select_from(ToolCall)
        .join(Message, ToolCall.message_id == Message.id)
        .join(ChatThread, Message.thread_id == ChatThread.id)
        .where(ToolCall.status != "running")
    )
    if tool:
        manual, manual_count = (
            manual.where(ToolRun.tool == tool),
            manual_count.where(ToolRun.tool == tool),
        )
        chat, chat_count = (
            chat.where(ToolCall.name == tool),
            chat_count.where(ToolCall.name == tool),
        )
    if actor_id is not None:
        manual = manual.where(ToolRun.actor_id == actor_id)
        manual_count = manual_count.where(ToolRun.actor_id == actor_id)
        chat = chat.where(ChatThread.user_id == actor_id)
        chat_count = chat_count.where(ChatThread.user_id == actor_id)

    entries = [
        RunEntry(
            id=r.id,
            tool=r.tool,
            trigger="manual",
            actor_email=r.actor_email,
            args=r.args,
            ok=r.ok,
            output=r.output,
            duration_ms=r.duration_ms,
            created_at=r.created_at,
        )
        for r in (
            await db.execute(manual.order_by(ToolRun.created_at.desc()).limit(window))
        ).scalars()
    ]
    for call, email, thread_id in (
        await db.execute(chat.order_by(ToolCall.started_at.desc()).limit(window))
    ).all():
        entries.append(
            RunEntry(
                id=call.id,
                tool=call.name,
                trigger="chat",
                actor_email=email,
                args=call.args or {},
                ok=call.status == "ok",
                output=(call.result if call.status == "ok" else call.error) or "",
                duration_ms=call.duration_ms or 0,
                created_at=call.started_at,
                thread_id=thread_id,
            )
        )
    entries.sort(key=lambda e: e.created_at, reverse=True)
    total = int((await db.execute(manual_count)).scalar_one()) + int(
        (await db.execute(chat_count)).scalar_one()
    )
    return entries[offset:window], total


__all__ = [
    "SERVER_NAME",
    "RunEntry",
    "ToolServiceError",
    "add_server",
    "delete_server",
    "list_servers",
    "mcp_tool_name",
    "refresh_server",
    "server_token",
    "set_mcp_policy",
    "set_server_enabled",
    "create_custom",
    "delete_custom",
    "list_custom",
    "list_runs",
    "load_into_registry",
    "run_tool",
    "set_enabled",
    "update_custom",
]
