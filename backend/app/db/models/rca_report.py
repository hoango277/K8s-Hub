"""Persist RCA runs, their evidence, and ranked hypotheses."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RcaRun(Base):
    __tablename__ = "rca_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="status_hop_le",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_name: Mapped[str] = mapped_column(String(253), nullable=False)
    namespace: Mapped[str] = mapped_column(String(253), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    evidence: Mapped[list[RcaEvidence]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )
    hypotheses: Mapped[list[RcaHypothesis]] = relationship(
        back_populates="run", cascade="all, delete-orphan", lazy="raise"
    )


class RcaEvidence(Base):
    __tablename__ = "rca_evidence"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rca_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[RcaRun] = relationship(back_populates="evidence", lazy="raise")


class RcaHypothesis(Base):
    __tablename__ = "rca_hypotheses"
    __table_args__ = (
        CheckConstraint("rank > 0", name="rank_duong"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_hop_le"),
        UniqueConstraint("run_id", "rank", name="uq_rca_hypotheses_run_rank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rca_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    run: Mapped[RcaRun] = relationship(back_populates="hypotheses", lazy="raise")
