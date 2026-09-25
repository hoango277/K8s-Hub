"""Configuration changed from the web UI, and the history of those changes.

`settings_overrides` is the persisted form of the in-memory overrides in
app/core/config.py: one row per field that currently differs from .env.
Without it every change made on the Settings page vanished on restart —
including API keys typed there — while the page claimed they were saved.

`settings_changes` is append-only: who changed which field, from what, to
what, and when. The execution mode decides whether the AI may change the
cluster on its own, so "who switched it to auto, and when" must always have
an answer.

Secrets (API keys):
  - in `settings_overrides` the value is ENCRYPTED (see settings_service.py);
  - in `settings_changes` the value is NEVER stored — only that it changed.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

FIELD_NAME_MAX = 64


class SettingOverride(Base):
    __tablename__ = "settings_overrides"

    name: Mapped[str] = mapped_column(String(FIELD_NAME_MAX), primary_key=True)
    # JSONB so lists (K8S_ALLOWED_NAMESPACES) and numbers keep their type.
    # For secrets this holds {"enc": "<Fernet token>"}, never the plain key.
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # SET NULL, not CASCADE: locking or (one day) removing an admin must not
    # silently revert the configuration they set.
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class SettingChange(Base):
    __tablename__ = "settings_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Copied, not only joined: the history must stay readable even if the
    # account is later renamed or its id is gone.
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    # update | restore (back to .env) | reset_all | reload_env
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # Null for actions that are not about one field (reload_env).
    field: Mapped[str | None] = mapped_column(String(FIELD_NAME_MAX), nullable=True)
    old_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    # When true, old_value/new_value are always null — keys are never logged.
    secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
