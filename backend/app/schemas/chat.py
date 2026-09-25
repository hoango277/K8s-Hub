"""Input/output types for the conversation endpoints.

Unlike `app/schemas/events.py` (what flows over SSE while the assistant is
running), this file describes what can be READ BACK afterwards: the
conversation list, message history, and stored tool calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant", "system"]
MessageStatus = Literal["streaming", "complete", "error"]
ToolCallStatus = Literal["running", "ok", "error"]


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        max_length=120,
        description="Leave empty to use the first question as the title",
    )
    cluster: str | None = Field(default=None, max_length=120)


class ThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class ThreadOut(BaseModel):
    """One row in the sidebar conversation list."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    cluster: str | None
    archived: bool
    created_at: datetime
    last_message_at: datetime | None


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: str
    name: str
    args: dict[str, Any]
    result: str | None
    status: ToolCallStatus
    error: str | None
    duration_ms: int | None
    started_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    role: MessageRole
    content: str

    # The reasoning, if the provider exposes it.
    reasoning: str | None = None

    position: int
    status: MessageStatus
    error: str | None
    created_at: datetime

    # Only assistant messages have these.
    trace_id: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None

    # Tokens spent. The `messages` table has stored these from the start, but
    # they used to be missing here so the API silently dropped them — from the
    # outside it looked as if the system could not count tokens. This is the
    # data source for the cost section of the observability page.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class ThreadDetail(ThreadOut):
    """A conversation with its full history — used when reopening an old conversation."""

    messages: list[MessageOut] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """What the user sends to start a response turn."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)

    # Overrides for this turn only; the global configuration is left untouched.
    provider: str | None = Field(
        default=None, description="Force the provider for this turn, e.g. 'google'"
    )
    model: str | None = Field(default=None, description="Force the model name for this turn")


__all__ = [
    "ChatRequest",
    "MessageOut",
    "MessageRole",
    "MessageStatus",
    "ThreadCreate",
    "ThreadDetail",
    "ThreadOut",
    "ThreadUpdate",
    "ToolCallOut",
    "ToolCallStatus",
]
