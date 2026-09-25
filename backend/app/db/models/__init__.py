"""Collects every table.

Alembic only sees tables that have been imported into `Base.metadata`, so every
new model MUST be listed here — otherwise `alembic revision --autogenerate`
will silently generate a migration that drops that table.
"""

from app.db.models.message import Message, ToolCall
from app.db.models.thread import ChatThread
from app.db.models.user import RefreshToken, User

__all__ = ["ChatThread", "Message", "RefreshToken", "ToolCall", "User"]
