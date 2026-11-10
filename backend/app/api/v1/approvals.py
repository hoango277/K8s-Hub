"""Human-in-the-loop approval of cluster changes proposed by the assistant.

    GET  /approvals                  the queue and history   (every role)
    GET  /approvals/summary          pending count, for the sidebar badge
    GET  /approvals/{id}             one change: plan, diff, dry-run, outcome
    POST /approvals/{id}/approve     run it                  (engineer+)
    POST /approvals/{id}/reject      refuse it, with a reason (engineer+)
    POST /approvals/{id}/verify      re-check a rollout      (engineer+)
    POST /approvals/{id}/revert      propose the reverse of an executed change (every role)

Everyone can SEE the queue — a user who asked for a change can follow it —
but only engineers and admins decide. The decision and the outcome are also
written back into the conversation the change came from. Proposing a revert is
open to every role for the same reason asking for a change in the chat is: it
only creates a pending proposal, which an engineer still has to approve.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DbSession, require_role
from app.db.models.approval import Approval
from app.db.models.user import User
from app.modules.nl_command import revert as revert_rules
from app.services import approval_service as svc

router = APIRouter()
Engineer = Annotated[User, Depends(require_role("engineer"))]

ApprovalStatus = Literal["pending", "executing", "executed", "failed", "rejected", "expired"]


class RiskFlag(BaseModel):
    """A tool output of the proposing turn that looked like planted instructions."""

    tool: str
    signals: list[str] = Field(
        description="Why it was flagged: addresses_ai, fake_system, override, conceal, "
        "names_write_tool, claims_approval"
    )


class RevertRef(BaseModel):
    """The latest revert proposed for a change."""

    id: uuid.UUID
    status: ApprovalStatus


class ApprovalOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    namespace: str | None
    target: str | None
    danger: Literal["caution", "dangerous"]
    source: str
    command: list[str] | None = Field(description="Custom-tool changes: the exact argv")
    diff: str | None
    dry_run_output: str | None
    status: ApprovalStatus
    reason: str | None
    result: str | None
    verify_ok: bool | None
    verify_message: str | None
    requested_by_email: str
    request_text: str | None = Field(
        description="What the user asked in the turn that produced this proposal"
    )
    risk_flags: list[RiskFlag] = Field(
        description="Possible prompt injection: flagged tool outputs read before proposing"
    )
    decided_by_email: str | None
    decided_at: datetime | None
    executed_at: datetime | None
    thread_id: uuid.UUID | None
    created_at: datetime
    expires_at: datetime
    reverts_id: uuid.UUID | None = Field(
        default=None, description="This change is the revert of that one"
    )
    revert: RevertRef | None = Field(
        default=None, description="The latest revert proposed for this change"
    )
    revertible: bool = Field(
        default=False, description="An executed change K8s-Hub knows how to revert"
    )
    revert_blocker: str | None = Field(
        default=None, description="Why this executed change can't be reverted"
    )


class ApprovalPage(BaseModel):
    items: list[ApprovalOut]
    total: int


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1000)


def _out(row: Approval, revert: tuple[uuid.UUID, str] | None = None) -> ApprovalOut:
    plan: dict[str, Any] = row.plan or {}
    blocker = revert_rules.blocker(row) if row.status == "executed" else None
    return ApprovalOut(
        reverts_id=row.reverts_id,
        revert=RevertRef(id=revert[0], status=revert[1]) if revert else None,  # type: ignore[arg-type]
        revertible=row.status == "executed" and blocker is None,
        revert_blocker=blocker,
        id=row.id,
        kind=row.kind,
        title=row.title,
        namespace=row.namespace,
        target=row.target,
        danger=row.danger,  # type: ignore[arg-type]
        source=row.source,
        command=plan.get("argv"),
        diff=row.diff,
        dry_run_output=row.dry_run_output,
        status=row.status,  # type: ignore[arg-type]
        reason=row.reason,
        result=row.result,
        verify_ok=row.verify_ok,
        verify_message=row.verify_message,
        requested_by_email=row.requested_by_email,
        request_text=row.request_text,
        risk_flags=[RiskFlag(**f) for f in row.risk_flags or []],
        decided_by_email=row.decided_by_email,
        decided_at=row.decided_at,
        executed_at=row.executed_at,
        thread_id=row.thread_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


async def _or_404(db: DbSession, approval_id: uuid.UUID) -> Approval:
    row = await svc.get(db, approval_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval not found.")
    return row


async def _full(db: DbSession, row: Approval) -> ApprovalOut:
    """One change, with its latest revert."""
    reverts = await svc.latest_reverts(db, [row.id])
    return _out(row, reverts.get(row.id))


@router.get("", response_model=ApprovalPage)
async def list_approvals(
    db: DbSession,
    _user: CurrentUser,
    status_filter: Annotated[ApprovalStatus | None, Query(alias="status")] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> ApprovalPage:
    rows, total = await svc.list_approvals(db, status=status_filter, limit=limit, offset=offset)
    reverts = await svc.latest_reverts(db, [r.id for r in rows])
    return ApprovalPage(items=[_out(r, reverts.get(r.id)) for r in rows], total=total)


@router.get("/summary")
async def summary(db: DbSession, _user: CurrentUser) -> dict[str, int]:
    return {"pending": await svc.pending_count(db)}


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: uuid.UUID, db: DbSession, _user: CurrentUser) -> ApprovalOut:
    return await _full(db, await _or_404(db, approval_id))


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(approval_id: uuid.UUID, db: DbSession, actor: Engineer) -> ApprovalOut:
    await _or_404(db, approval_id)
    try:
        row = await svc.approve(db, approval_id, actor)
    except svc.ApprovalError as exc:
        # 409: the approval exists but its state doesn't allow this any more.
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _full(db, row)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID, payload: RejectRequest, db: DbSession, actor: Engineer
) -> ApprovalOut:
    await _or_404(db, approval_id)
    try:
        row = await svc.reject(db, approval_id, actor, payload.reason)
    except svc.ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _full(db, row)


@router.post("/{approval_id}/verify", response_model=ApprovalOut)
async def reverify(approval_id: uuid.UUID, db: DbSession, _actor: Engineer) -> ApprovalOut:
    await _or_404(db, approval_id)
    try:
        row = await svc.reverify(db, approval_id)
    except svc.ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return await _full(db, row)


@router.post(
    "/{approval_id}/revert", response_model=ApprovalOut, status_code=status.HTTP_201_CREATED
)
async def revert(approval_id: uuid.UUID, db: DbSession, user: CurrentUser) -> ApprovalOut:
    """Propose the reverse of an executed change. Returns the NEW pending proposal;
    409 with the reason when it can't be reverted or a revert is already waiting."""
    await _or_404(db, approval_id)
    try:
        row = await svc.propose_revert(db, approval_id, user)
    except svc.ApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return _out(row)
