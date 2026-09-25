"""Read/write conversations.

This layer only touches the database — it knows nothing about the LLM and
nothing about HTTP. That makes it testable without calling a model, and
reusable from any endpoint.

Important convention: every function that fetches conversations takes `user`
and filters by owner itself. There is no "fetch any conversation by id"
function — so nobody can accidentally write an endpoint that lets one user read
another user's conversations.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models.message import Message, ToolCall
from app.db.models.thread import TITLE_MAX, ChatThread
from app.db.models.user import User

DEFAULT_TITLE = "New conversation"

# Number of most recent messages reloaded as context for a new turn. Capped so
# long conversations do not bloat the prompt and drive up cost.
HISTORY_LIMIT = 40


def title_from(content: str) -> str:
    """Use the first question as the title, trimmed to fit the sidebar."""
    compact = " ".join(content.split())
    if not compact:
        return DEFAULT_TITLE
    if len(compact) <= TITLE_MAX:
        return compact
    return compact[: TITLE_MAX - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


async def create_thread(
    db: AsyncSession,
    user: User,
    *,
    title: str | None = None,
    cluster: str | None = None,
) -> ChatThread:
    thread = ChatThread(
        user_id=user.id,
        title=(title or DEFAULT_TITLE)[:TITLE_MAX],
        cluster=cluster,
    )
    db.add(thread)
    await db.flush()
    return thread


async def list_threads(
    db: AsyncSession,
    user: User,
    *,
    include_archived: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[ChatThread]:
    stmt = select(ChatThread).where(ChatThread.user_id == user.id)
    if not include_archived:
        stmt = stmt.where(ChatThread.archived.is_(False))

    # A just-created conversation has no messages yet but must still sort to the top.
    sort_key = func.coalesce(ChatThread.last_message_at, ChatThread.created_at)

    stmt = stmt.order_by(sort_key.desc()).limit(limit).offset(offset)
    return (await db.execute(stmt)).scalars().all()


async def get_thread(
    db: AsyncSession, user: User, thread_id: uuid.UUID
) -> ChatThread | None:
    stmt = select(ChatThread).where(
        ChatThread.id == thread_id,
        ChatThread.user_id == user.id,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def update_thread(
    db: AsyncSession,
    thread: ChatThread,
    *,
    title: str | None = None,
    archived: bool | None = None,
) -> ChatThread:
    if title is not None:
        thread.title = title[:TITLE_MAX]
    if archived is not None:
        thread.archived = archived
    await db.flush()
    return thread


async def delete_thread(db: AsyncSession, thread: ChatThread) -> None:
    """Hard delete. Messages and tool calls go with it thanks to ON DELETE CASCADE."""
    await db.delete(thread)
    await db.flush()


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------


async def list_messages(
    db: AsyncSession,
    thread_id: uuid.UUID,
    *,
    limit: int | None = None,
) -> list[Message]:
    """History in order, with tool calls preloaded.

    `selectinload` is mandatory: the relationship is set to `lazy="raise"`, so
    reading `message.tool_calls` without preloading fails immediately instead of
    silently firing an extra query in the middle of the async flow.
    """
    stmt = (
        select(Message)
        .where(Message.thread_id == thread_id)
        .options(selectinload(Message.tool_calls))
    )

    if limit is None:
        return list((await db.execute(stmt.order_by(Message.position))).scalars().all())

    # We want the LAST N messages, so fetch in reverse and then flip.
    rows = list(
        (await db.execute(stmt.order_by(Message.position.desc()).limit(limit)))
        .scalars()
        .all()
    )
    rows.reverse()
    return rows


async def next_position(db: AsyncSession, thread_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.max(Message.position), 0)).where(
        Message.thread_id == thread_id
    )
    return int((await db.execute(stmt)).scalar_one()) + 1


async def add_user_message(
    db: AsyncSession, thread: ChatThread, content: str
) -> Message:
    """Store the user's question, and set the title if this is the first one."""
    position = await next_position(db, thread.id)

    message = Message(
        thread_id=thread.id,
        role="user",
        content=content,
        position=position,
        status="complete",
    )
    db.add(message)

    if position == 1 and thread.title == DEFAULT_TITLE:
        thread.title = title_from(content)
    thread.last_message_at = datetime.now(UTC)

    await db.flush()
    return message


async def start_assistant_message(
    db: AsyncSession,
    thread: ChatThread,
    *,
    provider: str | None = None,
    model: str | None = None,
    trace_id: str | None = None,
) -> Message:
    """Create the record up front, before the assistant starts talking.

    Having an id from the start means it can be sent down to the client, and if
    the server dies midway there is still a trace in the 'streaming' state
    instead of nothing at all.
    """
    message = Message(
        thread_id=thread.id,
        role="assistant",
        content="",
        position=await next_position(db, thread.id),
        status="streaming",
        provider=provider,
        model=model,
        trace_id=trace_id,
    )
    db.add(message)
    await db.flush()
    return message


async def finish_assistant_message(
    db: AsyncSession,
    message: Message,
    *,
    content: str,
    reasoning: str = "",
    tool_calls: Sequence[dict[str, Any]] = (),
    latency_ms: int | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    error: str | None = None,
) -> Message:
    """Finalize the answer and the tool calls that came with it.

    `tool_calls` is a list of flat dicts collected by the streaming layer —
    dicts rather than ORM objects so that layer does not have to import models.
    """
    message.content = content
    # Store an empty string as NULL: saves space and distinguishes 'none' from ''.
    message.reasoning = reasoning or None
    message.status = "error" if error else "complete"
    message.error = error
    message.latency_ms = latency_ms
    message.prompt_tokens = prompt_tokens
    message.completion_tokens = completion_tokens

    for tc in tool_calls:
        db.add(
            ToolCall(
                message_id=message.id,
                call_id=str(tc["call_id"])[:64],
                name=str(tc["name"])[:120],
                args=tc.get("args") or {},
                result=tc.get("result"),
                status=tc.get("status") or "ok",
                error=tc.get("error"),
                duration_ms=tc.get("duration_ms"),
                started_at=tc.get("started_at") or datetime.now(UTC),
            )
        )

    await db.flush()
    return message


__all__ = [
    "DEFAULT_TITLE",
    "HISTORY_LIMIT",
    "add_user_message",
    "create_thread",
    "delete_thread",
    "finish_assistant_message",
    "get_thread",
    "list_messages",
    "list_threads",
    "next_position",
    "start_assistant_message",
    "title_from",
    "update_thread",
]
