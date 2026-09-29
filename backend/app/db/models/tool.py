"""Tool catalog state, external MCP servers, and the history of manual tool runs.

What is NOT stored: the built-in tools themselves (they are code, in
app/modules/tools/builtin/). Only what changes at runtime lives here:
  - `tool_settings`: enabled/disabled per tool, and the danger level an
    engineer assigned to an external tool;
  - `mcp_servers` + `mcp_tools`: which servers are connected and the tools
    they last reported, so the catalog still shows them when a server is down;
  - `tool_runs`: who ran which tool from the Tools tab, with what input,
    and what came back. Chat tool calls are already in `tool_calls` + Langfuse.
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
    # read | write | destructive — only used for external (MCP) tools.
    danger: Mapped[str | None] = mapped_column(String(16), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class McpTool(Base):
    __tablename__ = "mcp_tools"

    server_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mcp_servers.id", ondelete="CASCADE"), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    input_schema: Mapped[Any] = mapped_column(JSONB, nullable=False)
    # What the SERVER claims. Shown as a hint, never trusted for safety.
    read_only_hint: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


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
