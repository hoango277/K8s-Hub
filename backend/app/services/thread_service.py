"""Đọc/ghi hội thoại.

Tầng này chỉ chạm CSDL — không biết gì về LLM, không biết gì về HTTP. Nhờ vậy
test được mà không cần gọi model, và endpoint nào cũng dùng lại được.

Quy ước quan trọng: mọi hàm lấy hội thoại đều nhận `user` và tự lọc theo chủ
sở hữu. Không có hàm nào lấy hội thoại "bất kỳ theo id" — để không ai vô tình
viết được endpoint cho phép đọc hội thoại của người khác.
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

DEFAULT_TITLE = "Hội thoại mới"

# Số tin nhắn gần nhất nạp lại làm ngữ cảnh cho lượt hỏi mới. Có giới hạn để
# hội thoại dài không làm phình prompt và đội chi phí.
HISTORY_LIMIT = 40


def title_from(content: str) -> str:
    """Lấy câu hỏi đầu tiên làm tiêu đề, cắt cho vừa thanh bên."""
    gon = " ".join(content.split())
    if not gon:
        return DEFAULT_TITLE
    if len(gon) <= TITLE_MAX:
        return gon
    return gon[: TITLE_MAX - 1].rstrip() + "…"


# --------------------------------------------------------------------------
# Hội thoại
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

    # Hội thoại vừa tạo chưa có tin nhắn nào, vẫn phải nằm trên đầu.
    thu_tu = func.coalesce(ChatThread.last_message_at, ChatThread.created_at)

    stmt = stmt.order_by(thu_tu.desc()).limit(limit).offset(offset)
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
    """Xoá hẳn. Tin nhắn và tool call đi theo nhờ ON DELETE CASCADE."""
    await db.delete(thread)
    await db.flush()


# --------------------------------------------------------------------------
# Tin nhắn
# --------------------------------------------------------------------------


async def list_messages(
    db: AsyncSession,
    thread_id: uuid.UUID,
    *,
    limit: int | None = None,
) -> list[Message]:
    """Lịch sử theo đúng thứ tự, kèm sẵn tool call.

    `selectinload` là bắt buộc: quan hệ đang để `lazy="raise"` nên đọc
    `message.tool_calls` mà chưa nạp sẵn sẽ báo lỗi ngay thay vì lặng lẽ bắn
    thêm truy vấn ở giữa luồng bất đồng bộ.
    """
    stmt = (
        select(Message)
        .where(Message.thread_id == thread_id)
        .options(selectinload(Message.tool_calls))
    )

    if limit is None:
        return list((await db.execute(stmt.order_by(Message.position))).scalars().all())

    # Muốn N tin nhắn CUỐI, nên lấy ngược rồi đảo lại.
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
    """Ghi câu hỏi của người dùng, và đặt tiêu đề nếu đây là câu đầu tiên."""
    vi_tri = await next_position(db, thread.id)

    message = Message(
        thread_id=thread.id,
        role="user",
        content=content,
        position=vi_tri,
        status="complete",
    )
    db.add(message)

    if vi_tri == 1 and thread.title == DEFAULT_TITLE:
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
    """Tạo sẵn bản ghi trước khi trợ lý bắt đầu nói.

    Có id ngay từ đầu thì gửi kèm được xuống client, và nếu máy chủ chết giữa
    chừng thì vẫn còn dấu vết ở trạng thái 'streaming' thay vì mất trắng.
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
    """Chốt câu trả lời và các lần gọi công cụ kèm theo.

    `tool_calls` là danh sách dict phẳng do tầng streaming gom lại — dùng dict
    thay vì đối tượng ORM để tầng đó không phải import model.
    """
    message.content = content
    # Chuỗi rỗng thì để NULL, đỡ tốn chỗ và phân biệt được 'không có' với ''.
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
