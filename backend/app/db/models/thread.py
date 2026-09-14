"""Một cuộc hội thoại.

Mỗi lần người dùng mở khung chat mới là một `ChatThread`. Lịch sử tin nhắn
nằm ở bảng `messages`, và chính lịch sử đó được nạp lại làm ngữ cảnh cho
lượt hỏi kế tiếp — hệ thống không dựa vào bộ nhớ tạm của tiến trình, nên
khởi động lại máy chủ vẫn không mất mạch hội thoại.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.message import Message
    from app.db.models.user import User

# Tiêu đề tự đặt từ câu hỏi đầu tiên, cắt bớt cho vừa thanh bên.
TITLE_MAX = 120


class ChatThread(Base, TimestampMixin):
    __tablename__ = "chat_threads"
    __table_args__ = (
        # Thanh bên luôn hỏi "hội thoại của tôi, mới nhất trước".
        Index("ix_chat_threads_user_moi_nhat", "user_id", "last_message_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(TITLE_MAX), nullable=False, default="Hội thoại mới")

    # Cụm đang thao tác. Để dạng chữ, chưa khoá ngoại sang bảng cluster vì
    # bảng đó chưa có; khi có thì đổi sang khoá ngoại trong một migration riêng.
    cluster: Mapped[str | None] = mapped_column(String(120), nullable=True)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Tách khỏi updated_at: sửa tiêu đề không được làm hội thoại nhảy lên đầu.
    last_message_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="threads", lazy="raise")
    messages: Mapped[list[Message]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.position",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<ChatThread {self.id} {self.title!r}>"
