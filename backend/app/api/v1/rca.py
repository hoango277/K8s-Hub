"""Root-cause analysis (Groot-style event graph, app/modules/rca).

    GET  /rca/targets                      namespaces a diagnosis may run in
    GET  /rca/targets/{ns}/workloads       workloads to focus on
    POST /rca/runs                         start a diagnosis (every role)
    GET  /rca/runs                         history
    GET  /rca/runs/{id}                    graph, hypotheses, report
    GET  /rca/runs/{id}/stream             SSE progress (step events, then done)
    POST /rca/runs/{id}/report             (re)write the AI report
    POST /rca/runs/{id}/fixes/{fix}/propose  turn a fix candidate into an approval
    POST /rca/alerts                       Alertmanager webhook (bearer token, no user)
    POST /rca/runs/{id}/hypotheses/{rank}/feedback   right / not it (engineer+)
    GET  /rca/weights                      what feedback has taught (engineer+)

Who sees what: a `user` sees their own runs and the ones the system started
(alerts, periodic scans); engineers and admins see all. Diagnosing is
read-only, so every role may start one — in the namespaces they may read
(K8S_ALLOWED_NAMESPACES). Proposing a fix only creates a pending approval;
deciding it still needs an engineer.
"""

from __future__ import annotations

import asyncio
import hmac
import uuid
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import defer
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentUser, DbSession, has_role, require_role
from app.core.config import get_settings
from app.db.models.rca import RcaHypothesis, RcaRun
from app.db.models.user import User
from app.db.session import get_sessionmaker
from app.integrations.k8s import resources as res
from app.integrations.k8s.client import K8sError
from app.modules.rca import learning, pipeline, remediation, triggers
from app.modules.rca import report as rca_report
from app.modules.tools.guard import ToolInputError, allowed_namespaces, check_namespace
from app.schemas.events import DoneEvent, ErrorEvent, EventStream, StepEvent
from app.schemas.rca import (
    FeedbackIn,
    HypothesisOut,
    ProposeFixOut,
    RcaRunCreate,
    RcaRunOut,
    RcaRunPage,
    RcaRunSummary,
    ReportRequest,
    WeightOut,
)
from app.services import approval_service as approvals

router = APIRouter()

STREAM_POLL_SECONDS = 1.0
STREAM_MAX_SECONDS = 600
SYSTEM_TRIGGERS = ("alert", "scan")


def _visible(user: User):
    """SQL filter: runs this user may see."""
    if has_role(user, ("engineer",)):
        return true()
    return or_(RcaRun.requested_by == user.id, RcaRun.trigger.in_(SYSTEM_TRIGGERS))


def _top_cause(run: RcaRun, top_event: str | None) -> tuple[str | None, str | None]:
    if run.report_status == "done" and run.report and run.report.get("summary"):
        cause = run.report["summary"]
    elif top_event:
        etype, _, entity = top_event.partition(":")
        cause = f"{etype} on {entity.replace('/-/', '/')}"
    else:
        cause = None
    return cause, (top_event.partition(":")[0] if top_event else None)


def _summary(run: RcaRun, top_event: str | None) -> RcaRunSummary:
    cause, cause_type = _top_cause(run, top_event)
    return RcaRunSummary(
        id=run.id, trigger=run.trigger, requested_by_email=run.requested_by_email,  # type: ignore[arg-type]
        namespace=run.namespace, target_kind=run.target_kind, target_name=run.target_name,  # type: ignore[arg-type]
        window_start=run.window_start, window_end=run.window_end, status=run.status,  # type: ignore[arg-type]
        error=run.error, report_status=run.report_status, created_at=run.created_at,  # type: ignore[arg-type]
        finished_at=run.finished_at, top_cause=cause, top_cause_type=cause_type,
    )  # fmt: skip


async def _get_visible(db: DbSession, run_id: uuid.UUID, user: User) -> RcaRun:
    run = await db.scalar(select(RcaRun).where(RcaRun.id == run_id, _visible(user)))
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Diagnosis not found.")
    return run


async def _hypotheses(db: DbSession, run_id: uuid.UUID) -> list[RcaHypothesis]:
    return list(
        (
            await db.scalars(
                select(RcaHypothesis)
                .where(RcaHypothesis.run_id == run_id)
                .order_by(RcaHypothesis.rank)
            )
        ).all()
    )


def _detail(run: RcaRun, hyps: list[RcaHypothesis]) -> RcaRunOut:
    base = _summary(run, hyps[0].event_id if hyps else None)
    return RcaRunOut(
        **base.model_dump(),
        steps=run.steps or [],
        warnings=run.warnings or [],
        graph=run.graph,
        hypotheses=[HypothesisOut.model_validate(h) for h in hyps],
        report=run.report,
        llm_trace_id=run.llm_trace_id,
        approval_id=run.approval_id,
    )


class TargetsOut(BaseModel):
    """What the New diagnosis form can offer."""

    namespaces: list[str]
    error: str | None = None


class WorkloadRef(BaseModel):
    kind: str
    name: str


@router.get("/targets", response_model=TargetsOut)
async def list_targets(_user: CurrentUser) -> TargetsOut:
    """Namespaces a diagnosis may run in (K8S_ALLOWED_NAMESPACES, or all)."""
    allowed = allowed_namespaces()
    try:
        items = await res.list_objects(await res.resolve_kind("namespace"), None, limit=500)
        names = sorted(i["metadata"]["name"] for i in items)
    except K8sError as exc:
        # The form still works with a typed namespace; say why the list is empty.
        return TargetsOut(namespaces=allowed, error=str(exc))
    return TargetsOut(namespaces=[n for n in names if not allowed or n in allowed])


@router.get("/targets/{namespace}/workloads", response_model=list[WorkloadRef])
async def list_workloads(namespace: str, _user: CurrentUser) -> list[WorkloadRef]:
    try:
        check_namespace(namespace)
    except ToolInputError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    out: list[WorkloadRef] = []
    for kind in ("Deployment", "StatefulSet", "DaemonSet"):
        try:
            items = await res.list_objects(
                await res.resolve_kind(kind.lower()), namespace, limit=500
            )
        except K8sError:
            continue
        out += [WorkloadRef(kind=kind, name=i["metadata"]["name"]) for i in items]
    return sorted(out, key=lambda w: w.name)


class AlertsAccepted(BaseModel):
    started: list[str]
    skipped: list[str]


@router.post("/alerts", response_model=AlertsAccepted)
async def alertmanager_webhook(
    payload: Annotated[dict[str, Any], Body()],
    authorization: Annotated[str | None, Header()] = None,
) -> AlertsAccepted:
    """Alertmanager webhook receiver (deploy/observability/alertmanager-rca.yaml).

    No user session: Alertmanager authenticates with the shared
    ALERTMANAGER_WEBHOOK_TOKEN as a bearer token. Answers 200 even when every
    alert is skipped — a non-2xx makes Alertmanager retry the same batch.
    """
    expected = get_settings().ALERTMANAGER_WEBHOOK_TOKEN
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The alert webhook is not enabled."
        )
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid webhook token.")
    return AlertsAccepted(**await triggers.handle_alerts(payload))


@router.post("/runs", response_model=RcaRunOut, status_code=status.HTTP_202_ACCEPTED)
async def start_run(payload: RcaRunCreate, user: CurrentUser) -> RcaRunOut:
    try:
        if payload.namespace:
            check_namespace(payload.namespace)
        if bool(payload.target_kind) != bool(payload.target_name):
            raise ToolInputError("Give both a target kind and a target name, or neither.")
        run = await pipeline.create_run(
            namespace=payload.namespace,
            trigger="manual",
            requested_by=user.id,
            requested_by_email=user.email,
            target_kind=payload.target_kind,
            target_name=payload.target_name,
            lookback_minutes=payload.lookback_minutes,
        )
    except (ToolInputError, ValueError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    pipeline.spawn(
        pipeline.run_with_report(
            run.id, with_report=payload.with_report, provider=payload.provider, model=payload.model
        )
    )
    return _detail(run, [])


@router.get("/runs", response_model=RcaRunPage)
async def list_runs(
    db: DbSession,
    user: CurrentUser,
    namespace: str | None = None,
    trigger: Annotated[str | None, Query(pattern="^(manual|chat|alert|scan)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RcaRunPage:
    where = [_visible(user)]
    if namespace:
        where.append(RcaRun.namespace == namespace)
    if trigger:
        where.append(RcaRun.trigger == trigger)
    total = await db.scalar(select(func.count()).select_from(RcaRun).where(*where)) or 0
    runs = (
        await db.scalars(
            select(RcaRun)
            .options(defer(RcaRun.graph))  # the graph is large and lists don't show it
            .where(*where)
            .order_by(RcaRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    tops = dict(
        (
            await db.execute(
                select(RcaHypothesis.run_id, RcaHypothesis.event_id).where(
                    RcaHypothesis.run_id.in_([r.id for r in runs]), RcaHypothesis.rank == 1
                )
            )
        ).all()
    )
    return RcaRunPage(items=[_summary(r, tops.get(r.id)) for r in runs], total=total)


@router.get("/runs/{run_id}", response_model=RcaRunOut)
async def get_run(run_id: uuid.UUID, db: DbSession, user: CurrentUser) -> RcaRunOut:
    run = await _get_visible(db, run_id, user)
    return _detail(run, await _hypotheses(db, run_id))


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, db: DbSession, user: CurrentUser) -> EventSourceResponse:
    """Progress as `step` events (replayed from the start), then `done`.

    Polls the row instead of an in-memory channel: progress survives a
    reload and works whichever worker process runs the analysis.
    """
    await _get_visible(db, run_id, user)

    async def events() -> AsyncIterator[dict[str, str]]:
        stream = EventStream()
        sent: dict[str, tuple[str, str]] = {}
        waited = 0.0
        while waited < STREAM_MAX_SECONDS:
            async with get_sessionmaker()() as s:
                run = await s.get(RcaRun, run_id)
            if run is None:
                return
            steps = list(run.steps or [])
            if run.report_status != "none":
                label, state = {
                    "running": ("Checking the hypotheses and writing the report", "running"),
                    "done": ("Report written", "done"),
                    "failed": ("The AI report could not be written", "error"),
                }[run.report_status]
                steps.append({"key": "report", "label": label, "status": state})
            for step in steps:
                current = (step["label"], step["status"])
                if sent.get(step["key"]) != current:
                    sent[step["key"]] = current
                    yield stream.emit(
                        StepEvent(key=step["key"], label=step["label"], status=step["status"])
                    )
            if run.status == "failed":
                yield stream.emit(
                    ErrorEvent(code="rca_failed", message=run.error or "The diagnosis failed.")
                )
                break
            if run.status == "completed" and run.report_status != "running":
                break
            await asyncio.sleep(STREAM_POLL_SECONDS)
            waited += STREAM_POLL_SECONDS
        yield stream.emit(DoneEvent(trace_id=None))

    return EventSourceResponse(events(), ping=15)


@router.post(
    "/runs/{run_id}/report", response_model=RcaRunOut, status_code=status.HTTP_202_ACCEPTED
)
async def rewrite_report(
    run_id: uuid.UUID, payload: ReportRequest, db: DbSession, user: CurrentUser
) -> RcaRunOut:
    run = await _get_visible(db, run_id, user)
    if run.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "The diagnosis hasn't finished yet.")
    if run.report_status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "A report is already being written.")
    run.report_status = "running"
    await db.commit()
    pipeline.spawn(rca_report.write_report(run_id, provider=payload.provider, model=payload.model))
    return _detail(run, await _hypotheses(db, run_id))


Engineer = Annotated[User, Depends(require_role("engineer"))]


@router.post("/runs/{run_id}/hypotheses/{rank}/feedback", response_model=HypothesisOut)
async def give_feedback(
    run_id: uuid.UUID, rank: int, payload: FeedbackIn, db: DbSession, user: Engineer
) -> HypothesisOut:
    """Mark a ranked cause right or wrong. Engineers only: it changes how every
    later diagnosis ranks (learning.py), so it is not for everyone to tune."""
    await _get_visible(db, run_id, user)
    hyp = await learning.record(run_id, rank, payload.correct, by=user.email)
    if hyp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This diagnosis has no cause at that rank.")
    return HypothesisOut.model_validate(hyp)


@router.get("/weights", response_model=list[WeightOut])
async def list_weights(_user: Engineer) -> list[WeightOut]:
    """What feedback has taught so far: per rule and per event type."""
    return [WeightOut(**row) for row in await learning.table()]


@router.post("/runs/{run_id}/fixes/{fix_id}/propose", response_model=ProposeFixOut)
async def propose_fix(
    run_id: uuid.UUID, fix_id: str, db: DbSession, user: CurrentUser
) -> ProposeFixOut:
    run = await _get_visible(db, run_id, user)
    hyps = await _hypotheses(db, run_id)
    fixes = {
        f.id: f
        for f in remediation.candidates(run.graph or {}, [h.chain or [h.event_id] for h in hyps])
    }
    fix = fixes.get(fix_id)
    if fix is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "This fix is not a candidate of the diagnosis."
        )
    if not fix.proposable:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This suggestion is advice only.")
    try:
        plan = await remediation.build_plan(fix)
        # Role "user" on purpose: a fix from RCA is never auto-executed, even
        # in auto mode — someone must read the diff (remediation.py).
        actor = approvals.Actor(id=user.id, email=user.email, role="user")
        row = await approvals.propose(
            plan,
            actor=actor,
            source="rca",
            request_text=f"Fix from diagnosis {run_id}: {fix.title}",
        )
    except (ToolInputError, ValueError) as exc:  # ApprovalError is a ValueError
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    run.approval_id = row.id
    await db.commit()
    return ProposeFixOut(approval_id=row.id, title=row.title, status=row.status)
