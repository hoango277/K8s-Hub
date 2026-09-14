"""Tập hợp mọi bảng.

Alembic chỉ nhìn thấy bảng nào đã được import vào `Base.metadata`, nên mọi
model mới BẮT BUỘC phải được liệt kê ở đây — nếu không, `alembic revision
--autogenerate` sẽ lặng lẽ sinh ra migration xoá mất bảng đó.
"""

from app.db.models.message import Message, ToolCall
from app.db.models.thread import ChatThread
from app.db.models.user import User

__all__ = ["ChatThread", "Message", "ToolCall", "User"]
