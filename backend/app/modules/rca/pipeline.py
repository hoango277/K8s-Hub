"""One RCA run, end to end.

    snapshot → topology → event history → detectors → causal graph → ranking
    (→ optional LLM verification + report, report.py)

`analyze()` is the deterministic part: no database, no LLM, a few seconds.
`execute_run()` wraps it for a stored run (`rca_runs`): it records each step
as it goes, so the SSE endpoint can replay progress to whoever opens the page
— also after a reload, because the steps live in the row, not in memory.

Runs execute as asyncio tasks inside the backend process (there is no worker
queue in this project yet): a backend restart mid-run leaves the run
"running"; `mark_interrupted()` at startup turns those into failed runs.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.telemetry import record_rca_run
from app.db.models.approval import Approval
from app.db.models.rca import RcaHypothesis, RcaRun
from app.db.session import get_sessionmaker
from app.modules.rca import causality, events_store, learning, ranking, snapshot, topology
from app.modules.rca.causality import CausalGraph
from app.modules.rca.detectors import (
    Context,
    Found,
    changes,
    dependencies,
    logs,
    metrics,
    nodes,
    pods,
    traces,
    workloads,
)
from app.modules.rca.model import Entity, Event, Hypothesis

logger = logging.getLogger(__name__)

MAX_STORED_EVENTS = 300
MAX_STORED_DEPENDENCIES = 200
TARGET_KINDS = ("Workload", "Pod", "Service")
# `rca_runs.namespace` of a whole-cluster diagnosis.
CLUSTER = "*"

StepCallback = Callable[[str, str, str], Awaitable[None]]


@dataclass
class Analysis:
    namespace: str  # the focus, or CLUSTER
    start: datetime
    end: datetime
    target: Entity | None
    events: list[Event]
    graph: CausalGraph
    hypotheses: list[Hypothesis]
    warnings: list[str] = field(default_factory=list)
    # Namespaces actually analysed (focus + its dependencies); None = all.
    scope: list[str] | None = None
    dependencies: list[dict[str, Any]] = field(default_factory=list)

    def event(self, event_id: str) -> Event | None:
        return self.graph.events.get(event_id) or next(
            (e for e in self.events if e.id == event_id), None
        )

    def graph_json(self) -> dict[str, Any]:
        in_graph = set(self.graph.events)
        # Graph events first, so a cut never drops what the ranking used.
        ordered = sorted(self.events, key=lambda e: (e.id not in in_graph, e.start))
        return {
            "events": [
                {**e.to_json(), "in_graph": e.id in in_graph} for e in ordered[:MAX_STORED_EVENTS]
            ],
            "edges": [e.to_json() for e in self.graph.edges],
            "seeds": self.graph.seeds,
            "namespaces": self.scope if self.scope is not None else [CLUSTER],
            "dependencies": self.dependencies[:MAX_STORED_DEPENDENCIES],
        }


def target_entity(namespace: str, kind: str | None, name: str | None) -> Entity | None:
    if not kind or not name:
        return None
    if kind not in TARGET_KINDS:
        raise ValueError(f"target kind must be one of {', '.join(TARGET_KINDS)}")
    return (
        topology.workload(namespace, name) if kind == "Workload" else Entity(kind, namespace, name)
    )


async def load_approvals(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Changes K8s-Hub itself applied in the window — Groot's "developer activity".

    Every namespace: the changes detector keeps those in scope, and the scope
    may grow after this is read (dependencies found in logs and traces).
    """
    async with get_sessionmaker()() as db:
        rows = (
            await db.scalars(
                select(Approval).where(
                    Approval.executed_at.is_not(None),
                    Approval.executed_at >= start,
                    Approval.executed_at <= end,
                    Approval.status.in_(("executed", "failed")),
                )
            )
        ).all()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "namespace": r.namespace,
            "target": r.target,
            "status": r.status,
            "executed_at": r.executed_at,
            "requested_by_email": r.requested_by_email,
            "decided_by_email": r.decided_by_email,
        }
        for r in rows
    ]


async def _noop(_key: str, _label: str, _status: str) -> None:
    return None


def _focus(namespace: str | None) -> str | None:
    return None if namespace in (None, "", CLUSTER) else namespace


async def _detect(ctx: Context, found: Found) -> None:
    for detector in (pods, workloads, nodes, changes):
        await detector.detect(ctx, found)
    # Independent queries to three backends: run them together. Each one
    # catches its own failures and leaves a warning.
    await asyncio.gather(*(d.detect(ctx, found) for d in (metrics, logs, traces)))


async def analyze(
    namespace: str | None,
    *,
    end: datetime | None = None,
    lookback_minutes: int | None = None,
    target_kind: str | None = None,
    target_name: str | None = None,
    on_step: StepCallback = _noop,
    with_approvals: bool = True,
) -> Analysis:
    """Diagnose `namespace` and the namespaces it depends on — or, with None or
    CLUSTER, the whole cluster."""
    end = end or datetime.now(UTC)
    minutes = lookback_minutes or get_settings().RCA_LOOKBACK_MINUTES
    start = end - timedelta(minutes=minutes)
    focus = _focus(namespace)
    target = target_entity(focus, target_kind, target_name) if focus else None

    await on_step("snapshot", "Reading the cluster", "running")
    snap = await snapshot.take()
    topo = topology.build(snap)
    await on_step(
        "snapshot",
        f"Read {len(snap.pods)} pods in {len(snap.namespaces)} namespaces",
        "done",
    )

    await on_step("dependencies", "Finding what talks to what", "running")
    warnings = list(snap.warnings)
    if problem := await dependencies.discover(topo, end, minutes):
        warnings.append(problem)
    # Groot builds the dependency graph AROUND the alerted service: the focus
    # namespace plus whatever its workloads call, two hops out.
    scope = topo.dependency_namespaces({focus}) if focus else None
    await on_step(
        "dependencies",
        f"{len(topo.dependencies)} service dependencies; analysing "
        + (", ".join(sorted(scope)) if scope is not None else "the whole cluster"),
        "done",
    )

    await on_step("events", "Collecting Kubernetes events", "running")
    scope_list = sorted(scope) if scope is not None else None
    kevents, event_warnings = await events_store.in_window(scope_list, start, end, snap.events)
    warnings += event_warnings
    approvals: list[dict[str, Any]] = []
    if with_approvals:
        try:
            approvals = await load_approvals(start, end)
        except Exception as exc:  # the DB being down must not stop a diagnosis
            logger.warning("RCA could not read approvals: %s", exc)
            warnings.append("Changes made through K8s-Hub could not be read.")
    await on_step("events", f"Collected {len(kevents)} Kubernetes events", "done")

    ctx = Context(snap, topo, kevents, start, end, approvals=approvals, warnings=warnings,
                  namespaces=scope)  # fmt: skip
    found = Found()
    await on_step(
        "detect", "Looking for anomalies in state, changes, metrics, logs, traces", "running"
    )
    await _detect(ctx, found)

    # Logs and traces may have revealed dependencies the configuration didn't
    # name ("connection refused to pg-rw.database…"): analyse those namespaces too.
    if scope is not None:
        extra = topo.dependency_namespaces({focus}) - scope
        if extra:
            more, more_warnings = await events_store.in_window(
                sorted(extra), start, end, snap.events
            )
            ctx2 = Context(snap, topo, more, start, end, approvals=approvals,
                           warnings=more_warnings, namespaces=extra)  # fmt: skip
            await _detect(ctx2, found)
            ctx.warnings += ctx2.warnings
            scope |= extra
    events = found.all()
    await on_step("detect", f"Found {len(events)} events", "done")

    await on_step("graph", "Linking events with causal rules", "running")
    # Learned from feedback (learning.py); like approvals, it needs the database.
    weights = await learning.load() if with_approvals else learning.NEUTRAL
    graph, graph_warnings = causality.build(
        events, topo, start, target=target, focus={focus} if focus else None, weights=weights
    )
    await on_step(
        "graph", f"Linked {len(graph.events)} events with {len(graph.edges)} edges", "done"
    )

    await on_step("rank", "Ranking root-cause candidates", "running")
    hypotheses = ranking.rank(graph, weights=weights)
    await on_step("rank", f"Ranked {len(hypotheses)} candidates", "done")

    deps = [
        d
        for d in topo.dependencies_json()
        if scope is None or any(f"/{ns}/" in f"{d['caller']} {d['callee']}" for ns in scope)
    ]
    return Analysis(
        focus or CLUSTER, start, end, target, events, graph, hypotheses,
        warnings=[*ctx.warnings, *graph_warnings],
        scope=sorted(scope) if scope is not None else None,
        dependencies=deps,
    )  # fmt: skip


# --- stored runs ----------------------------------------------------------------------

# Strong references to running tasks: asyncio keeps only weak ones, and a
# garbage-collected task silently stops mid-run.
_tasks: set[asyncio.Task[Any]] = set()


async def create_run(
    *,
    namespace: str | None,
    trigger: str,
    requested_by: uuid.UUID | None,
    requested_by_email: str,
    target_kind: str | None = None,
    target_name: str | None = None,
    lookback_minutes: int | None = None,
    end: datetime | None = None,
    alert_fingerprint: str | None = None,
) -> RcaRun:
    """`namespace` None = the whole cluster (stored as CLUSTER); a target needs a namespace."""
    focus = _focus(namespace)
    if focus is None and target_name:
        raise ValueError("Pick a namespace to focus on a workload.")
    if focus is not None:
        target_entity(focus, target_kind, target_name)  # validate before storing
    namespace = focus or CLUSTER
    end = end or datetime.now(UTC)
    minutes = lookback_minutes or get_settings().RCA_LOOKBACK_MINUTES
    async with get_sessionmaker()() as db:
        run = RcaRun(
            id=uuid.uuid4(),
            trigger=trigger,
            requested_by=requested_by,
            requested_by_email=requested_by_email,
            namespace=namespace,
            target_kind=target_kind if target_name else None,
            target_name=target_name or None,
            window_start=end - timedelta(minutes=minutes),
            window_end=end,
            status="pending",
            steps=[],
            warnings=[],
            report_status="none",
            alert_fingerprint=alert_fingerprint,
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)
        return run


async def _record_step(run_id: uuid.UUID, key: str, label: str, status: str) -> None:
    async with get_sessionmaker()() as db:
        run = await db.get(RcaRun, run_id)
        if run is None:
            return
        steps = [s for s in run.steps if s.get("key") != key]
        # Keep the original position of a step that changes status.
        position = next((i for i, s in enumerate(run.steps) if s.get("key") == key), len(steps))
        steps.insert(position, {"key": key, "label": label, "status": status})
        run.steps = steps
        await db.commit()


async def execute_run(run_id: uuid.UUID, *, with_report: bool) -> Analysis | None:
    """Run the analysis for a stored run and save the result. Never raises."""
    async with get_sessionmaker()() as db:
        run = await db.get(RcaRun, run_id)
        if run is None:
            return None
        run.status, run.started_at = "running", datetime.now(UTC)
        params = (run.namespace, run.window_end, run.window_start, run.target_kind, run.target_name)
        trigger = run.trigger
        await db.commit()
    namespace, end, start, target_kind, target_name = params

    async def on_step(key: str, label: str, status: str) -> None:
        await _record_step(run_id, key, label, status)

    started = time.perf_counter()
    try:
        analysis = await analyze(
            namespace,
            end=end,
            lookback_minutes=int((end - start).total_seconds() // 60),
            target_kind=target_kind,
            target_name=target_name,
            on_step=on_step,
        )
    except Exception as exc:
        logger.exception("RCA run %s failed", run_id)
        record_rca_run(trigger=trigger, outcome="error", seconds=time.perf_counter() - started)
        await _finish(run_id, error=f"The analysis failed: {exc}"[:500])
        return None
    record_rca_run(trigger=trigger, outcome="ok", seconds=time.perf_counter() - started)

    await _save_analysis(run_id, analysis)
    if with_report:
        await report_job(run_id)
    return analysis


async def report_job(
    run_id: uuid.UUID, *, provider: str | None = None, model: str | None = None
) -> None:
    from app.modules.rca import report  # LLM imports are heavy; load on demand

    await report.write_report(run_id, provider=provider, model=model)


async def run_with_report(
    run_id: uuid.UUID, *, with_report: bool, provider: str | None = None, model: str | None = None
) -> None:
    """The background job of a run: analysis, then (optionally) the AI report."""
    analysis = await execute_run(run_id, with_report=False)
    if analysis is not None and with_report:
        await report_job(run_id, provider=provider, model=model)


async def record_analysis(run_id: uuid.UUID, analysis: Analysis) -> None:
    """Store an analysis computed outside a run (the scanner analyses first,
    and only creates a run when it finds something new)."""
    async with get_sessionmaker()() as db:
        await db.execute(
            update(RcaRun)
            .where(RcaRun.id == run_id)
            .values(
                status="running",
                started_at=datetime.now(UTC),
                steps=[{"key": "scan", "label": "Found by the periodic scan", "status": "done"}],
            )
        )
        await db.commit()
    await _save_analysis(run_id, analysis)


async def _save_analysis(run_id: uuid.UUID, analysis: Analysis) -> None:
    async with get_sessionmaker()() as db:
        run = await db.get(RcaRun, run_id)
        if run is None:
            return
        run.graph = analysis.graph_json()
        run.warnings = analysis.warnings
        for h in analysis.hypotheses:
            db.add(
                RcaHypothesis(
                    run_id=run_id, rank=h.rank, event_id=h.event_id, score=h.score,
                    chain=h.chain, rules=h.rules,
                )
            )  # fmt: skip
        run.status, run.finished_at = "completed", datetime.now(UTC)
        await db.commit()


async def _finish(run_id: uuid.UUID, *, error: str) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(
            update(RcaRun)
            .where(RcaRun.id == run_id)
            .values(status="failed", error=error, finished_at=datetime.now(UTC))
        )
        await db.commit()


def spawn(coro: Awaitable[Any]) -> asyncio.Task[Any]:
    task = asyncio.ensure_future(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def mark_interrupted() -> int:
    """At startup: runs left running by a previous process will never finish."""
    async with get_sessionmaker()() as db:
        result = await db.execute(
            update(RcaRun)
            .where(RcaRun.status.in_(("pending", "running")))
            .values(
                status="failed",
                error="The backend restarted during this analysis. Run it again.",
                finished_at=datetime.now(UTC),
            )
        )
        await db.execute(
            update(RcaRun).where(RcaRun.report_status == "running").values(report_status="failed")
        )
        await db.commit()
        return result.rowcount or 0


__all__ = [
    "Analysis",
    "analyze",
    "create_run",
    "execute_run",
    "mark_interrupted",
    "record_analysis",
    "report_job",
    "run_with_report",
    "spawn",
    "target_entity",
]
