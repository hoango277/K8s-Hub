"""Agent Skills stored in the database, and the history of script runs.

- `skills`: one row per skill that has state — every CUSTOM skill (created or
  imported on the web), plus a BUILT-IN skill once someone disables it. The
  built-in skills' files stay in the repo (backend/skills/), never here.
- `skill_files`: the files of custom skills, path -> bytes, exactly as in the
  folder format (SKILL.md, scripts/…, references/…, assets/…), so export to a
  .zip is lossless.
- `skill_runs`: every script run, from the chat or the Skills page: who, which
  script, which arguments, the exit status and the output. Scripts run on the
  backend (see app/modules/skills/scripts.py), so this trail matters.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

SKILL_NAME_MAX = 64


class SkillRecord(Base):
    __tablename__ = "skills"

    name: Mapped[str] = mapped_column(String(SKILL_NAME_MAX), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # builtin | custom
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillFile(Base):
    __tablename__ = "skill_files"

    skill_name: Mapped[str] = mapped_column(
        String(SKILL_NAME_MAX),
        ForeignKey("skills.name", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    path: Mapped[str] = mapped_column(String(200), primary_key=True)
    # Bytes, not text: assets may be images or other binaries.
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SkillRun(Base):
    __tablename__ = "skill_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    skill: Mapped[str] = mapped_column(String(SKILL_NAME_MAX), nullable=False, index=True)
    script: Mapped[str] = mapped_column(String(200), nullable=False)
    args: Mapped[Any] = mapped_column(JSONB, nullable=False)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)  # chat | manual
    actor_email: Mapped[str] = mapped_column(String(320), nullable=False)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output: Mapped[str] = mapped_column(Text, nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
