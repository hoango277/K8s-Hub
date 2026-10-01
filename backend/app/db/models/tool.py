"""Tool catalog state, custom tools, and the history of manual tool runs.

What is NOT stored: the built-in tools themselves (they are code, in
app/modules/tools/builtin/). Only what changes at runtime lives here:
  - `tool_settings`: enabled/disabled per tool;
  - `custom_tools`: CLI tools engineers define on the web (kubectl-ai style);
  - `tool_runs`: who ran which tool from the Tools tab, with what input,
    and what came back. Chat tool calls are already in `tool_calls` + Langfuse.

  - `mcp_servers` + `mcp_tools`: external MCP servers an engineer connected,
    the tools they last reported, and each tool's policy (enabled, needs
    approval). Removed on 30/09/2026, back on 01/10/2026 behind engineer-only
    management and a per-tool approval choice.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

TOOL_NAME_MAX = 64


class ToolSetting(Base):
    __tablename__ = "tool_settings"

    name: Mapped[str] = mapped_column(String(TOOL_NAME_MAX), primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class CustomTool(Base):
    """A CLI wrapped as a tool, as kubectl-ai's custom tools are.

    The model writes the ARGUMENTS (never the program): `command` is fixed
    here. A call whose arguments start with one of `read_only_prefixes` runs
    at once in the sandbox; anything else is a change and goes through the
    approval flow (dry-run where the CLI supports it, then a human decides).
    """

    __tablename__ = "custom_tools"

    # Becomes the model's tool name, so a slug; unique across all tools.
    name: Mapped[str] = mapped_column(String(TOOL_NAME_MAX), primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # When to use it — what the model reads to decide.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # The program, e.g. "kubectl", "helm". One word, no path, no arguments.
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    # Syntax and examples for the model (kubectl-ai's `command_desc`).
    usage: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # e.g. ["get", "describe", "logs", "rollout status"]
    read_only_prefixes: Mapped[Any] = mapped_column(JSONB, nullable=False, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class McpServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Becomes the prefix of every tool name (`<name>__<tool>`), so it is a slug.
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Bearer token, ENCRYPTED (app/core/crypto.py). Never returned by the API.
    token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class McpTool(Base):
    """A tool the server reported, with the policy an engineer set for it.

    Defaults are the safe side: disabled, and every call waits for approval.
    `read_only_hint` is what the SERVER claims — shown, never trusted.
    """

    __tablename__ = "mcp_tools"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[Any] = mapped_column(JSONB, nullable=False)
    read_only_hint: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    policy_updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    policy_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ToolRun(Base):
    __tablename__ = "tool_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tool: Mapped[str] = mapped_column(String(TOOL_NAME_MAX), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    args: Mapped[Any] = mapped_column(JSONB, nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
