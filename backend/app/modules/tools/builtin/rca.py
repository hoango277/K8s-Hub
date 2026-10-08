"""Built-in tool: root-cause diagnosis from the chat (app/modules/rca).

Runs the deterministic part of RCA (detectors → causal graph → ranking) in a
few seconds and returns the top hypotheses, each with its causal chain and
one quote of evidence. It does NOT run the RCA report step: the chat model
already plays that role — it can explain the result and call other read tools.

The run is stored like any diagnosis (trigger "chat"), so the answer links to
the Diagnosis page where the whole graph and evidence are shown.
"""

from __future__ import annotations

from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.modules.rca import pipeline
from app.modules.tools.guard import ToolInputError, check_namespace, clamp
from app.modules.tools.schema import Category, Danger, ToolSpec
from app.services.approval_service import actor_from_config


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


TOOLS = [ToolSpec(diagnose_incident, "Diagnose incident", Category.DIAGNOSIS, Danger.READ)]
