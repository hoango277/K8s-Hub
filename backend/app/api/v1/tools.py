"""Tool catalog, custom CLI tools, external MCP servers, and manual runs.

    GET    /tools                          catalog (every role)
    GET    /tools/runs                     run history (engineers see all, users their own)
    GET    /tools/custom/templates         starting points: kubectl, helm (engineer+)
    POST   /tools/custom                   create a custom tool   (engineer+)
    PUT    /tools/custom/{name}            edit it                (engineer+)
    DELETE /tools/custom/{name}            delete it              (engineer+)
    GET    /tools/mcp/servers              connected MCP servers  (every role)
    POST   /tools/mcp/servers              connect one            (engineer+)
    PATCH  /tools/mcp/servers/{id}         enable / disable it    (engineer+)
    POST   /tools/mcp/servers/{id}/refresh re-read its tools      (engineer+)
    DELETE /tools/mcp/servers/{id}         disconnect it          (engineer+)
    GET    /tools/{name}                   one tool
    PATCH  /tools/{name}                   enable; MCP tools also requires_approval (engineer+)
    POST   /tools/{name}/run               run it with arguments  (every role)

Roles follow CLAUDE.md: users run tools, engineers add and change them, admin
passes every check. Running a WRITE tool only proposes a change: it lands in
the approval queue like one proposed in the chat.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DbSession, has_role, require_role
from app.db.models.tool import CustomTool, McpServer
from app.db.models.user import User
from app.modules.tools.custom import TEMPLATES, CustomToolDef
from app.modules.tools.registry import registry
from app.modules.tools.schema import Danger, ToolSpec
from app.services import tool_service as svc

router = APIRouter()
Engineer = Annotated[User, Depends(require_role("engineer"))]


class CustomToolFields(BaseModel):
    """What an engineer writes to define a custom tool."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    description: str = Field(
        min_length=10, max_length=1000, description="When the assistant should use it"
    )
    command: str = Field(min_length=1, max_length=64, description="The program, e.g. kubectl")
    usage: str = Field(default="", max_length=4000, description="Syntax and examples")
    read_only_prefixes: list[str] = Field(
        default_factory=list, description="Subcommands that only read, e.g. 'get'"
    )
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    enabled: bool = True


class CustomToolCreate(CustomToolFields):
    name: str = Field(min_length=2, max_length=40)


class CustomToolOut(CustomToolCreate):
    model_config = ConfigDict(extra="ignore")


class McpToolInfo(BaseModel):
    server: str
    read_only_hint: bool | None = Field(
        description="What the MCP server CLAIMS about the tool — shown, never trusted"
    )
    requires_approval: bool


class ToolOut(BaseModel):
    name: str
    title: str
    description: str
    category: str
    source: str = Field(description="'builtin' or 'custom'")
    danger: Danger
    enabled: bool
    available: bool
    unavailable_reason: str | None = Field(description="Why it can't run now, if it can't")
    in_chat: bool = Field(description="Whether the assistant can call it right now")
    input_schema: dict[str, Any]
    custom: CustomToolOut | None = Field(default=None, description="Custom tools: the definition")
    mcp: McpToolInfo | None = Field(default=None, description="MCP tools: server and policy")


class ToolPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool | None = None
    requires_approval: bool | None = Field(
        default=None, description="MCP tools only: whether each call waits for approval"
    )


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


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    args: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: uuid.UUID
    tool: str
    trigger: Literal["manual", "chat"] = Field(
        default="manual",
        description="Run by hand from the Tools tab, or called by the assistant in a chat",
    )
    thread_id: uuid.UUID | None = Field(default=None, description="Chat runs: the conversation")
    actor_email: str
    args: dict[str, Any]
    ok: bool
    output: str
    duration_ms: int
    created_at: datetime


class RunPage(BaseModel):
    items: list[RunOut]
    total: int


def _custom_out(d: CustomToolDef) -> CustomToolOut:
    return CustomToolOut(
        name=d.name,
        title=d.title,
        description=d.description,
        command=d.command,
        usage=d.usage,
        read_only_prefixes=list(d.read_only_prefixes),
        timeout_seconds=d.timeout_seconds,
        enabled=d.enabled,
    )


def _tool_out(spec: ToolSpec) -> ToolOut:
    reason = registry.can_run(spec)
    custom = registry.custom_def(spec.name)
    rec = registry.mcp_record(spec.name)
    return ToolOut(
        name=spec.name,
        title=spec.title,
        description=spec.description,
        category=spec.category.value,
        source=spec.source,
        danger=spec.danger,
        enabled=registry.is_enabled(spec),
        available=spec.unavailable() is None,
        unavailable_reason=reason,
        in_chat=reason is None,
        input_schema=spec.input_schema(),
        custom=_custom_out(custom) if custom else None,
        mcp=McpToolInfo(
            server=rec.server_name,
            read_only_hint=rec.read_only_hint,
            requires_approval=rec.requires_approval,
        )
        if rec
        else None,
    )


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


def _spec_or_404(name: str) -> ToolSpec:
    spec = registry.get(name)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No tool named {name!r}.")
    return spec


async def _custom_or_404(db: DbSession, name: str) -> CustomTool:
    row = await db.get(CustomTool, name)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No custom tool named {name!r}.")
    return row


def _to_def(name: str, payload: CustomToolFields) -> CustomToolDef:
    return CustomToolDef(name=name, **payload.model_dump())


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
    # Users see their own runs only — the history carries other people's
    # inputs. Filtered in the query, so totals and paging stay right.
    own = None if has_role(user, ("engineer",)) else user.id
    items, total = await svc.list_runs(db, tool=tool, limit=limit, offset=offset, actor_id=own)
    return RunPage(
        items=[RunOut.model_validate(r, from_attributes=True) for r in items], total=total
    )


# --- custom tools ------------------------------------------------------------


@router.get("/custom/templates", response_model=list[CustomToolOut])
async def custom_templates(_actor: Engineer) -> list[CustomToolOut]:
    taken = {s.name for s in registry.all()}
    return [_custom_out(t) for t in TEMPLATES if t.name not in taken]


@router.post("/custom", response_model=ToolOut, status_code=status.HTTP_201_CREATED)
async def create_custom(payload: CustomToolCreate, db: DbSession, actor: Engineer) -> ToolOut:
    fields = CustomToolFields(**payload.model_dump(exclude={"name"}))
    try:
        await svc.create_custom(db, _to_def(payload.name, fields), actor=actor)
    except svc.ToolServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return _tool_out(_spec_or_404(payload.name))


@router.put("/custom/{name}", response_model=ToolOut)
async def update_custom(
    name: str, payload: CustomToolFields, db: DbSession, _actor: Engineer
) -> ToolOut:
    row = await _custom_or_404(db, name)
    try:
        await svc.update_custom(db, row, _to_def(name, payload))
    except svc.ToolServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return _tool_out(_spec_or_404(name))


@router.delete("/custom/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_custom(name: str, db: DbSession, _actor: Engineer) -> None:
    row = await _custom_or_404(db, name)
    await svc.delete_custom(db, row)
    await db.commit()


# --- MCP servers ---------------------------------------------------------------


@router.get("/mcp/servers", response_model=list[ServerOut])
async def list_servers(db: DbSession, _user: CurrentUser) -> list[ServerOut]:
    return [_server_out(s, n) for s, n in await svc.list_servers(db)]


@router.post("/mcp/servers", response_model=ServerOut, status_code=status.HTTP_201_CREATED)
async def add_server(payload: ServerCreate, db: DbSession, actor: Engineer) -> ServerOut:
    try:
        server = await svc.add_server(
            db, actor=actor, name=payload.name, url=payload.url, token=payload.token or None
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
        if payload.requires_approval is not None:
            if registry.mcp_record(name) is None:
                raise svc.ToolServiceError(
                    "Only MCP tools have an approval setting: built-in and custom tools decide "
                    "per call (reads run, changes wait for approval)."
                )
            await svc.set_mcp_policy(
                db, name, actor=actor, enabled=payload.enabled,
                requires_approval=payload.requires_approval,
            )
        elif payload.enabled is not None:
            await svc.set_enabled(db, spec, actor=actor, enabled=payload.enabled)
    except svc.ToolServiceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return _tool_out(registry.get(name) or spec)


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
