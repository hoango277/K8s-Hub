"""Built-in tools: root-cause diagnosis from the chat (app/modules/rca).

diagnose_incident runs the deterministic part of RCA (detectors → causal graph
→ ranking) in a few seconds and returns the top hypotheses, each with its
causal chain and one quote of evidence. It does NOT run the RCA report step:
the chat model already plays that role — it can explain the result and call
other read tools. The run is stored like any diagnosis (trigger "chat"), so the
answer links to the Diagnosis page where the whole graph and evidence are shown.

get_diagnosis reads a run already saved — the one a conversation was opened
from with "Ask in chat", or any id the user pastes. Its findings quote logs,
annotations and pod names, so they reach the model as a TOOL result (marked
untrusted by the injection guard, like all cluster data), never through the
system prompt.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlalchemy import select

from app.db.models.approval import Approval
from app.db.models.rca import RcaHypothesis, RcaRun
from app.db.session import get_sessionmaker
from app.modules.rca import access, pipeline, remediation
from app.modules.skills.matching import event_type, skills_for
from app.modules.tools.guard import ToolInputError, check_namespace, clamp
from app.modules.tools.schema import Category, Danger, ToolSpec
from app.services.approval_service import actor_from_config

logger = logging.getLogger(__name__)

MAX_DIAGNOSIS_CHARS = 5000
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
# DNS-1123 names, as Kubernetes allows them: what may appear in a system prompt.
_DNS_NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")


def safe_name(value: str | None) -> str | None:
    """The name if it is a plain Kubernetes name, else None. Run targets come
    from forms and alert labels; only names this strict go into a system prompt."""
    return value if value and _DNS_NAME.match(value) else None


def target_label(run: RcaRun) -> str:
    """'namespace langfuse', 'Workload rca-lab/api', 'the whole cluster'."""
    if run.namespace == "*":
        return "the whole cluster"
    ns = safe_name(run.namespace)
    if ns is None:
        return "a namespace"
    name = safe_name(run.target_name)
    if run.target_kind in ("Workload", "Pod", "Service") and name:
        return f"{run.target_kind} {ns}/{name}"
    return f"namespace {ns}"


def conversation_context(run: RcaRun) -> str:
    """System-prompt section for a thread opened from this diagnosis.

    Only K8s-Hub's own data: the run id, its target (strict names only, see
    safe_name) and window. What the diagnosis FOUND quotes cluster data, so it
    is read with get_diagnosis and arrives marked untrusted.
    """
    window = f"{run.window_start:%Y-%m-%d %H:%M}–{run.window_end:%H:%M} UTC"
    return (
        "CONVERSATION CONTEXT\n"
        f"- The user opened this conversation from diagnosis {run.id}: {target_label(run)}, "
        f"{window}.\n"
        f'- Before answering about it, call get_diagnosis with run_id "{run.id}" to read its '
        "ranked causes, evidence, next steps, suggested skills and fixes. Read it again rather "
        "than relying on earlier turns.\n"
        "- When a suggested skill fits the question, call load_skill and follow it."
    )


def _entity(entity: dict[str, Any] | None) -> str:
    e = entity or {}
    kind = e.get("sub") or e.get("kind") or "object"
    where = f"{e['namespace']}/" if e.get("namespace") else ""
    return f"{kind} {where}{e.get('name')}"


def describe_run(
    run: RcaRun, hyps: list[RcaHypothesis], *, fix_approval: tuple[str, str] | None = None
) -> str:
    """A saved diagnosis as text for the model: what was found, how sure, what next."""
    window = f"{run.window_start:%Y-%m-%d %H:%M}–{run.window_end:%H:%M} UTC"
    lines = [
        f"Diagnosis {run.id} of {target_label(run)} ({window}), started by "
        f"{run.requested_by_email} ({run.trigger}). Status: {run.status}."
    ]
    if run.status in ("pending", "running"):
        lines.append("It is still running: read it again in a few seconds.")
        return "\n".join(lines)
    if run.status == "failed":
        lines.append(f"It failed: {run.error or 'unknown error'}.")
        return "\n".join(lines)

    graph = run.graph or {}
    events = {e.get("id"): e for e in graph.get("events") or []}
    report = run.report if run.report_status == "done" and run.report else {}
    verdicts = {v.get("rank"): v for v in report.get("verdicts") or []}
    if report.get("summary"):
        lines.append(f"AI summary: {report['summary']}")
    if report.get("root_cause_rank"):
        lines.append(f"The AI picked cause #{report['root_cause_rank']} as the root cause.")
    if not hyps:
        lines.append("No cause was ranked: nothing anomalous was detected in this window.")

    for h in hyps:
        ev = events.get(h.event_id) or {}
        verdict = verdicts.get(h.rank) or {}
        status = f", AI: {verdict['status']}" if verdict.get("status") else ""
        title = ev.get("title") or event_type(h.event_id)
        where = _entity(ev.get("entity"))
        lines.append(f"\n#{h.rank} {title} on {where} (score {h.score:.2f}{status})")
        chain = [(events.get(eid) or {}).get("title") or event_type(eid) for eid in h.chain[1:]]
        if chain:
            lines.append("   leads to: " + " → ".join(chain))
        if verdict.get("reason"):
            lines.append(f"   AI reason: {verdict['reason']}")
        if verdict.get("next_steps"):
            lines.append("   next steps: " + "; ".join(verdict["next_steps"]))
        evidence = ev.get("evidence") or []
        if evidence:
            lines.append(f"   evidence: [{evidence[0].get('source')}] {evidence[0].get('text')}")
        skills = skills_for(h.chain or [h.event_id])
        if skills:
            names = ", ".join(s.name for s in skills)
            lines.append(f"   suggested skill: {names} (load_skill to follow it)")
        if h.feedback:
            judged = "the root cause" if h.feedback == "correct" else "NOT the cause"
            lines.append(f"   an engineer marked it {judged}")

    fixes = remediation.candidates(graph, [h.chain or [h.event_id] for h in hyps])
    if fixes:
        picked = (report.get("fix") or {}).get("id")
        lines.append("\nFix candidates (proposed from the diagnosis page; an engineer approves):")
        for f in fixes[:5]:
            note = "" if f.proposable else " (advice only)"
            lines.append(f"- {f.title}{note}" + (" ← the AI's pick" if f.id == picked else ""))
    if fix_approval:
        change_id, change_status = fix_approval
        lines.append(f"A fix was already proposed: change #{change_id[:8]} is {change_status}.")
    if run.warnings:
        lines.append("\nData gaps: " + " ".join(run.warnings[:3]))
    lines.append(f"\nFull graph and evidence: /rca/{run.id}")
    lines.append(
        "These are ranked candidates from causal rules, not proof: check the cause with the "
        "read tools before stating it as fact."
    )
    text = "\n".join(lines)
    if len(text) > MAX_DIAGNOSIS_CHARS:
        tail = f"\n… (cut — the rest is on /rca/{run.id})"
        text = text[: MAX_DIAGNOSIS_CHARS - len(tail)].rstrip() + tail
    return text


def format_result(run_id: Any, analysis: pipeline.Analysis) -> str:
    if analysis.scope is None:
        where = "the whole cluster"
    else:
        others = [n for n in analysis.scope if n != analysis.namespace]
        where = f"namespace {analysis.namespace}"
        if others:
            where += f" and its dependencies ({', '.join(others)})"
    lines = [
        f"Diagnosis of {where} "
        f"({analysis.start:%H:%M}–{analysis.end:%H:%M} UTC): "
        f"{len(analysis.events)} events, {len(analysis.graph.edges)} causal links.",
    ]
    if not analysis.hypotheses:
        lines.append("No event could be ranked as a cause: nothing anomalous was detected.")
    for h in analysis.hypotheses:
        ev = analysis.event(h.event_id)
        if ev is None:
            continue
        lines.append(f"\n#{h.rank} (score {h.score:.2f}) {ev.kind.title}: {ev.summary}")
        chain = [analysis.event(eid) for eid in h.chain[1:]]
        if chain:
            lines.append("   chain: " + " → ".join(e.kind.title for e in chain if e))
        if ev.evidence:
            lines.append(f"   evidence: {ev.evidence[0].text}")
    if analysis.warnings:
        lines.append("\nData gaps: " + " ".join(analysis.warnings[:3]))
    lines.append(f"\nFull graph and evidence: /rca/{run_id}")
    lines.append(
        "These are ranked candidates from causal rules, not proof: check the top one "
        "(e.g. describe_pod, get_pod_logs, pod_metrics) before stating it as the cause."
    )
    return "\n".join(lines)


@tool(parse_docstring=True)
async def diagnose_incident(
    namespace: str | None = None,
    workload: str | None = None,
    since_minutes: int = 120,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """Find the likely root cause of a problem in a namespace or the whole cluster (RCA).

    Use when the user asks WHY something is broken, slow or failing — before
    reading pods and logs one by one. It detects events (crashes, OOM kills,
    failing probes, rollouts, config edits, scaling, node pressure, error
    spikes), links them with causal rules and ranks root-cause candidates.

    Args:
        namespace: Kubernetes namespace to diagnose; the namespaces it depends on
            (databases, other services) are included automatically. Leave empty to
            diagnose the whole cluster.
        workload: optional Deployment/StatefulSet/DaemonSet name to focus on.
        since_minutes: how far back to look for causes, 15–1440 (default 120).
    """
    minutes = clamp(since_minutes, 15, 1440)
    target_kind = "Workload" if workload else None
    try:
        if namespace:
            check_namespace(namespace)
            pipeline.target_entity(namespace, target_kind, workload)
        elif workload:
            raise ToolInputError("Give the workload's namespace too.")
    except (ToolInputError, ValueError) as exc:
        return str(exc)
    actor = actor_from_config(config)
    try:
        run = await pipeline.create_run(
            namespace=namespace or None,
            trigger="chat",
            requested_by=actor.id,
            requested_by_email=actor.email,
            target_kind=target_kind,
            target_name=workload or None,
            lookback_minutes=minutes,
        )
    except Exception:
        # No database: still answer, the analysis itself doesn't need it.
        analysis = await pipeline.analyze(
            namespace or None, lookback_minutes=minutes, target_kind=target_kind,
            target_name=workload, with_approvals=False,
        )  # fmt: skip
        return format_result(None, analysis).replace(
            "Full graph and evidence: /rca/None", "(Not saved: the database is unavailable.)"
        )
    analysis = await pipeline.execute_run(run.id, with_report=False)
    if analysis is None:
        return f"The diagnosis failed; see /rca/{run.id} for the error."
    return format_result(run.id, analysis)


@tool(parse_docstring=True)
async def get_diagnosis(
    run_id: str,
    config: RunnableConfig = None,  # type: ignore[assignment]
) -> str:
    """Read a saved diagnosis (RCA run): ranked causes with evidence, the AI's verdicts and
    next steps, suggested skills and fix candidates.

    Use it when the conversation is about a diagnosis — it was opened from one, or the
    user gives a diagnosis id or a /rca/<id> link. It reads what was found; to look
    again at the cluster now, use diagnose_incident.

    Args:
        run_id: the diagnosis id (a UUID); a /rca/<id> link works too.
    """
    match = _UUID.search(run_id or "")
    if match is None:
        return "Give the diagnosis id: a UUID such as 65deb42b-747a-4d76-bff7-8d3ac6944889."
    rid = uuid.UUID(match.group(0))
    # Same rule as the Diagnosis page: a user reads their own runs and the system's.
    actor = actor_from_config(config)
    try:
        async with get_sessionmaker()() as db:
            run = await access.get_visible(db, rid, actor)
            if run is None:
                return f"Diagnosis {rid} was not found, or this user may not see it."
            hyps = list(
                (
                    await db.scalars(
                        select(RcaHypothesis)
                        .where(RcaHypothesis.run_id == rid)
                        .order_by(RcaHypothesis.rank)
                    )
                ).all()
            )
            fix = None
            if run.approval_id:
                row = await db.get(Approval, run.approval_id)
                fix = (str(row.id), row.status) if row else None
    except Exception:
        logger.exception("Could not read diagnosis %s", rid)
        return "Couldn't read the diagnosis: the database is unavailable right now."
    return describe_run(run, hyps, fix_approval=fix)


TOOLS = [
    ToolSpec(diagnose_incident, "Diagnose incident", Category.DIAGNOSIS, Danger.READ),
    ToolSpec(get_diagnosis, "Read diagnosis", Category.DIAGNOSIS, Danger.READ),
]
