"""One root-cause analysis run, and its ranked hypotheses.

A run is a snapshot of what K8s-Hub concluded at that moment — the cluster
moves on, so the graph, the evidence and the report are stored as they were
(JSONB), not recomputed. Evidence lives inside `graph` (each event carries its
own quotes): it is never queried on its own, so a table for it would only add
joins.

Rows are kept: they are the incident history the team reviews later, and the
RCA evaluation (backend/rca_eval) scores them.
"""

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
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

RCA_TRIGGERS = ("manual", "chat", "alert", "scan")
RCA_STATUSES = ("pending", "running", "completed", "failed")
REPORT_STATUSES = ("none", "running", "done", "failed")


class RcaRun(Base):
    __tablename__ = "rca_runs"
    __table_args__ = (
        CheckConstraint("trig IN ('manual', 'chat', 'alert', 'scan')", name="trigger"),
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed')", name="status"),
        CheckConstraint(
            "report_status IN ('none', 'running', 'done', 'failed')", name="report_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # `trigger` is a reserved word in SQL; the column is `trig`.
    trigger: Mapped[str] = mapped_column("trig", String(16), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_email: Mapped[str] = mapped_column(String(320), nullable=False)

    namespace: Mapped[str] = mapped_column(String(63), nullable=False, index=True)
    # Optional focus: Workload / Pod / Service name. None = the whole namespace.
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"key", "label", "status"}] — progress, replayed to late SSE subscribers.
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # {"events": [...], "edges": [...], "seeds": [...], "in_graph": [...]}
    graph: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    # The LLM's verification + write-up (app/modules/rca/report.py).
    report_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    llm_trace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # The fix proposed from this run, if someone asked for it.
    approval_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("approvals.id", ondelete="SET NULL"), nullable=True
    )
    # Alertmanager runs: deduplicates repeated notifications of one alert.
    alert_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    hypotheses: Mapped[list[RcaHypothesis]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="RcaHypothesis.rank",
        lazy="raise",
    )


class RcaHypothesis(Base):
    __tablename__ = "rca_hypotheses"
    __table_args__ = (UniqueConstraint("run_id", "rank", name="uq_rca_hypotheses_run_rank"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rca_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(400), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    # Event ids from this cause down to a symptom, and the rule ids between them.
    chain: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    rules: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # Set by the LLM step: confirmed | refuted | unclear.
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # A person's judgement (engineer+), or the ground truth of an evaluation
    # scenario: correct | wrong. Feeds rca_weights (app/modules/rca/learning.py).
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[RcaRun] = relationship(back_populates="hypotheses", lazy="raise")


class RcaWeight(Base):
    """What feedback taught: how often a rule / an event type was right or wrong.

    Key `rule:<id>` or `type:<EventType>`. The factor applied to the rule's
    weight or the type's prior is computed from these counts at analysis time
    (learning.factor) — storing counts, not the factor, keeps the smoothing
    changeable without rewriting history.
    """

    __tablename__ = "rca_weights"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    positive: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    negative: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


__all__ = [
    "RCA_STATUSES",
    "RCA_TRIGGERS",
    "REPORT_STATUSES",
    "RcaHypothesis",
    "RcaRun",
    "RcaWeight",
]
