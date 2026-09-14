"""Người dùng hệ thống.

Chưa có đăng nhập thật. Bảng này tồn tại để mọi hội thoại đều gắn được với
một chủ sở hữu ngay từ đầu — khi thêm đăng nhập sau này thì không phải sửa
lại khoá ngoại và không phải viết migration vá dữ liệu cũ.

Xem `app/api/deps.py` để biết người dùng mặc định lúc chạy local.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.thread import ChatThread

# Ai được làm gì — kiểm tra thật sẽ nằm ở app/core/permissions.py.
ROLES = ("viewer", "operator", "admin")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('viewer', 'operator', 'admin')",
            name="role_hop_le",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    threads: Mapped[list[ChatThread]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
