"""Tin nhắn và các lần gọi công cụ kèm theo.

Hai bảng này là thứ cho phép mở lại một hội thoại cũ và thấy ĐÚNG những gì
đã diễn ra: không chỉ câu trả lời cuối cùng, mà cả trợ lý đã tra cứu gì,
tham số ra sao, mất bao lâu, thành công hay lỗi.

Vì sao lưu tool call thành bảng riêng chứ không nhét vào JSON của tin nhắn:
thống kê sau này ("công cụ nào hay lỗi nhất", "trung bình mất bao lâu")
chỉ cần một câu truy vấn, không phải bóc JSON.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.thread import ChatThread

ROLES = ("user", "assistant", "system")
MESSAGE_STATUSES = ("streaming", "complete", "error")
TOOL_STATUSES = ("running", "ok", "error")


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant', 'system')", name="role_hop_le"),
        CheckConstraint(
            "status IN ('streaming', 'complete', 'error')", name="status_hop_le"
        ),
        # Hai tin nhắn trong cùng hội thoại không được trùng số thứ tự.
        UniqueConstraint("thread_id", "position", name="uq_messages_thread_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    thread_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_threads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Phần mô hình tự nghĩ trước khi trả lời. Lưu lại để mở lại hội thoại cũ
    # vẫn xem được nó đã suy luận thế nào — đó thường là chỗ duy nhất giải
    # thích vì sao trợ lý chọn tra cứu cái này mà không tra cái kia.
    # NULL với tin nhắn của người dùng, và với nhà cung cấp không lộ suy luận.
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Thứ tự trong hội thoại, bắt đầu từ 1. Không dựa vào created_at vì hai
    # tin nhắn có thể được ghi trong cùng một mili giây.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="complete")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Dấu vết để soi lại (use case observability) ---
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    thread: Mapped[ChatThread] = relationship(back_populates="messages", lazy="raise")
    tool_calls: Mapped[list[ToolCall]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        order_by="ToolCall.started_at",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<Message {self.role} #{self.position} {self.content[:30]!r}>"


class ToolCall(Base, TimestampMixin):
    __tablename__ = "tool_calls"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'ok', 'error')", name="status_hop_le"),
        # `call_id` do LangGraph sinh; trùng nhau trong cùng một tin nhắn là lỗi ghép cặp.
        UniqueConstraint("message_id", "call_id", name="uq_tool_calls_message_call"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Mã dùng để ghép tool_call_start với tool_call_end trên đường truyền.
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    # Bản rút gọn để hiển thị. Bản đầy đủ nằm ở Langfuse.
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    message: Mapped[Message] = relationship(back_populates="tool_calls", lazy="raise")

    def __repr__(self) -> str:
        return f"<ToolCall {self.name} {self.status}>"
