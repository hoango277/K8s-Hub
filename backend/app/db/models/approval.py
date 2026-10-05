"""A change to the cluster proposed by the assistant, waiting for (or past) a human decision.

One row is both the approval request AND its audit trail: who asked, what
exactly would run (`plan`), what the server-side dry-run said, the diff shown
to the approver, who decided, what running it returned and whether the
re-check afterwards passed. Rows are never deleted.

What gets executed is `plan`, stored at proposal time — never a new answer
from the model. What the approver saw is what runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

APPROVAL_STATUSES = ("pending", "executing", "executed", "failed", "rejected", "expired")


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'executing', 'executed', 'failed', 'rejected', 'expired')",
            name="status",
        ),
        CheckConstraint("danger IN ('caution', 'dangerous')", name="danger"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # scale | restart | set_image | delete_pod | apply | command
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    namespace: Mapped[str | None] = mapped_column(String(63), nullable=True, index=True)
    target: Mapped[str | None] = mapped_column(String(300), nullable=True)
    danger: Mapped[str] = mapped_column(String(16), nullable=False, default="caution")
    # The tool that proposed it (scale_workload, a custom tool's name…).
    source: Mapped[str] = mapped_column(String(64), nullable=False)

    plan: Mapped[Any] = mapped_column(JSONB, nullable=False)
    diff: Mapped[str | None] = mapped_column(Text, nullable=True)
    dry_run_output: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    verify_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    verify_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_email: Mapped[str] = mapped_column(String(320), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # "auto" when K8S_EXECUTION_MODE=auto executed it without a human.
    decided_by_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Where it came from, so the decision can be reported back into the chat.
    thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_threads.id", ondelete="SET NULL"), nullable=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # What the user asked in the turn that produced this proposal, and the tool
    # outputs of that turn that looked like planted instructions
    # ([{"tool": "get_pod_logs", "signals": ["addresses_ai", …]}]). Shown side by
    # side on the approval card: "asked: why is checkout slow?" next to "scale
    # payments to 0" is how an indirect prompt injection gets caught
    # (app/modules/nl_command/injection.py). NULL for rows from before, and for
    # proposals made outside a chat turn (the Tools tab).
    request_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
