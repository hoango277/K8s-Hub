"""Tool catalog, manual runs, and external MCP servers.

    GET    /tools                        catalog (every role)
    GET    /tools/runs                   run history (engineers see all, users their own)
    GET    /tools/mcp/servers            connected MCP servers (every role)
    POST   /tools/mcp/servers            connect a server            (engineer+)
    PATCH  /tools/mcp/servers/{id}       enable / disable it         (engineer+)
    POST   /tools/mcp/servers/{id}/refresh  re-read its tools        (engineer+)
    DELETE /tools/mcp/servers/{id}       disconnect it               (engineer+)
    GET    /tools/{name}                 one tool
    PATCH  /tools/{name}                 enable/disable, danger for external tools (engineer+)
    POST   /tools/{name}/run             run a READ tool with arguments (every role)

Roles follow CLAUDE.md: users run tools, engineers add and change them, admin
passes every check. Only read-only tools run — anything that changes the
cluster waits for the approval flow.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DbSession, has_role, require_role
from app.db.models.tool import McpServer
from app.db.models.user import User
from app.modules.tools.registry import registry
from app.modules.tools.schema import Danger, ToolSpec
from app.services import tool_service as svc

router = APIRouter()
Engineer = Annotated[User, Depends(require_role("engineer"))]


class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    category: str
    source: str = Field(description="'builtin' or 'mcp:<server>'")
    danger: Danger
    enabled: bool
    available: bool
    unavailable_reason: str | None = Field(description="Why it can't run now, if it can't")
    in_chat: bool = Field(description="Whether the assistant can call it right now")
    input_schema: dict[str, Any]
    read_only_hint: bool | None = Field(
        default=None, description="External tools only: what the MCP server claims (not trusted)"
    )


class ToolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    danger: Danger | None = Field(default=None, description="External (MCP) tools only")


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: uuid.UUID
    tool: str
    actor_email: str
    args: dict[str, Any]
    ok: bool
    output: str
    duration_ms: int
    created_at: datetime


class RunPage(BaseModel):
    items: list[RunOut]
    total: int


class ServerOut(BaseModel):
    id: uuid.UUID
    name: str
    url: str
    enabled: bool
    has_token: bool
    tool_count: int
    last_error: str | None
    refreshed_at: datetime | None


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=32)
    url: str = Field(min_length=8, max_length=500)
    token: str | None = Field(default=None, max_length=4000)


class ServerPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _tool_out(spec: ToolSpec) -> ToolOut:
    reason = registry.can_run(spec)
    meta = registry.mcp_meta(spec.name)
    return ToolOut(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        category=spec.category.value,
        source=spec.source,
        danger=registry.danger(spec),
        enabled=registry.is_enabled(spec),
        available=spec.unavailable() is None,
        unavailable_reason=reason,
        in_chat=reason is None,
        input_schema=spec.input_schema(),
        read_only_hint=meta.read_only_hint if meta else None,
    )


def _spec_or_404(name: str) -> ToolSpec:
    spec = registry.get(name)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tool named {name!r}.")
    return spec


def _server_out(server: McpServer, tool_count: int) -> ServerOut:
    return ServerOut(
        id=server.id,
        name=server.name,
        url=server.url,
        enabled=server.enabled,
        has_token=bool(server.token_enc),
        tool_count=tool_count,
        last_error=server.last_error,
        refreshed_at=server.refreshed_at,
    )


async def _server_or_404(db: DbSession, server_id: uuid.UUID) -> McpServer:
    server = await db.get(McpServer, server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")
    return server


async def _server_view(db: DbSession, server_id: uuid.UUID) -> ServerOut:
    for server, count in await svc.list_servers(db):
        if server.id == server_id:
            return _server_out(server, count)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found.")


# --- catalog ---------------------------------------------------------------


@router.get("", response_model=list[ToolOut])
async def list_tool_catalog(_user: CurrentUser) -> list[ToolOut]:
    return [_tool_out(s) for s in registry.all()]


# --- runs (declared before /{name} so "runs" isn't read as a tool name) --------


@router.get("/runs", response_model=RunPage)
async def list_runs(
    db: DbSession,
    user: CurrentUser,
    tool: str | None = Query(None, max_length=64),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> RunPage:
    items, total = await svc.list_runs(db, tool=tool, limit=limit, offset=offset)
    if not has_role(user, ("engineer",)):
        # Users see their own runs only; the history carries other people's inputs.
        items = [r for r in items if r.actor_id == user.id]
        total = len(items) if total <= limit else total
    return RunPage(
        items=[RunOut.model_validate(r, from_attributes=True) for r in items], total=total
    )


# --- MCP servers ---------------------------------------------------------------


@router.get("/mcp/servers", response_model=list[ServerOut])
async def list_servers(db: DbSession, _user: CurrentUser) -> list[ServerOut]:
    return [_server_out(s, n) for s, n in await svc.list_servers(db)]


@router.post("/mcp/servers", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
async def add_server(payload: ServerCreate, db: DbSession, _actor: Engineer) -> ServerOut:
    try:
        server = await svc.add_server(
            db, name=payload.name, url=payload.url, token=payload.token or None
        )
    except svc.ToolServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return await _server_view(db, server.id)


@router.patch("/mcp/servers/{server_id}", response_model=ServerOut)
async def update_server(
    server_id: uuid.UUID, payload: ServerPatch, db: DbSession, _actor: Engineer
) -> ServerOut:
    server = await _server_or_404(db, server_id)
    await svc.set_server_enabled(db, server, payload.enabled)
    await db.commit()
    return await _server_view(db, server_id)


@router.post("/mcp/servers/{server_id}/refresh", response_model=ServerOut)
async def refresh_server(server_id: uuid.UUID, db: DbSession, _actor: Engineer) -> ServerOut:
    server = await _server_or_404(db, server_id)
    await svc.refresh_server(db, server)
    await db.commit()
    return await _server_view(db, server_id)


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_server(server_id: uuid.UUID, db: DbSession, _actor: Engineer) -> None:
    server = await _server_or_404(db, server_id)
    await svc.delete_server(db, server)
    await db.commit()


# --- one tool -----------------------------------------------------------------


@router.get("/{name}", response_model=ToolOut)
async def get_tool(name: str, _user: CurrentUser) -> ToolOut:
    return _tool_out(_spec_or_404(name))


@router.patch("/{name}", response_model=ToolOut)
async def update_tool(name: str, payload: ToolPatch, db: DbSession, actor: Engineer) -> ToolOut:
    spec = _spec_or_404(name)
    try:
        await svc.update_tool(db, spec, actor=actor, enabled=payload.enabled, danger=payload.danger)
    except svc.ToolServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return _tool_out(spec)


@router.post("/{name}/run", response_model=RunOut)
async def run_tool(name: str, payload: RunRequest, db: DbSession, user: CurrentUser) -> RunOut:
    spec = _spec_or_404(name)
    try:
        run = await svc.run_tool(db, spec, actor=user, args=payload.args)
    except svc.ToolServiceError as exc:
        # 409: the request is fine, the tool just can't run in its current state.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return RunOut.model_validate(run, from_attributes=True)
