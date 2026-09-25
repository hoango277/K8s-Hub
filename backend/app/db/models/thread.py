"""A single conversation.

Every time a user opens a new chat, that is one `ChatThread`. The message
history lives in the `messages` table, and that very history is reloaded as
context for the next turn — the system does not rely on in-process memory, so
restarting the server does not lose the thread of the conversation.
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

# The title is set automatically from the first question, trimmed to fit the sidebar.
TITLE_MAX = 120


class ChatThread(Base, TimestampMixin):
    __tablename__ = "chat_threads"
    __table_args__ = (
        # The sidebar always asks for "my conversations, newest first".
        # (Index name kept as-is: it already exists in the migrations.)
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
    title: Mapped[str] = mapped_column(
        String(TITLE_MAX), nullable=False, default="New conversation"
    )

    # The cluster being operated on. Stored as text, with no foreign key to a
    # cluster table yet because that table does not exist; once it does, switch
    # to a foreign key in a dedicated migration.
    cluster: Mapped[str | None] = mapped_column(String(120), nullable=True)

    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Separate from updated_at: renaming a conversation must not bump it to the top.
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
