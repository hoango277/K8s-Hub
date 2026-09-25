"""Tools the assistant is allowed to call from the chat panel.

THIS IS THE ONLY ATTACHMENT POINT. To let the assistant do something new, add
a tool to `get_tools()` — don't modify the graph and don't modify the
streaming layer.

Safety boundaries — read carefully before adding one:

  1. Tools in this file are READ-ONLY. No tool creates/edits/deletes resources
     on the cluster. Mutations go through a separate path: the assistant
     proposes a structured description, the system dry-runs it, a human
     approves, and only then is it executed.
  2. No raw command strings. There is no tool like `run_kubectl(cmd)` —
     parameters must be discrete fields so they can be checked before running.
  3. The tool description is what the model reads to decide whether to call
     it. Write a vague description and the model will call it at the wrong
     time, and that bug is very hard to track down.

Cluster lookups so far cover TRACES only (Grafana Tempo, see
app/integrations/tempo/client.py). Pods, events, logs and metrics come once
their clients are written (app/integrations/k8s, loki, prometheus).
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings
from app.integrations.llm.client import describe_config
from app.integrations.tempo import client as tempo


@tool
def system_info(config: RunnableConfig) -> str:
    """Report how the K8s Hub system is currently configured.

    Use when the user asks which AI model the system is running, which
    execution mode it is in, or which namespaces it is allowed to act on.
    """
    # `config` is injected by LangChain and is NOT in the schema the model sees
    # — so the model cannot (and need not) pass anything for this parameter.
    #
    # The provider and model are taken from here rather than from the global
    # configuration: users can pick a model for a SINGLE chat turn. Reading the
    # global configuration would make the assistant misreport itself right
    # after the user switched models in the UI.
    meta = (config or {}).get("metadata") or {}
    llm = describe_config(
        provider=meta.get("llm_provider"), model=meta.get("llm_model")
    )

    settings = get_settings()

    mode_description = {
        "read_only": "read-only, no changes are made",
        "require_approval": "changes must be approved by a human before running",
        "auto": "changes are applied automatically, WITHOUT human approval",
    }.get(settings.K8S_EXECUTION_MODE, settings.K8S_EXECUTION_MODE)

    namespaces = settings.K8S_ALLOWED_NAMESPACES or ["(all)"]

    return (
        f"AI model: {llm['provider']} / {llm['model']}\n"
        f"Tool calling: {'yes' if llm['tool_calling'] else 'no'}\n"
        f"Execution mode: {settings.K8S_EXECUTION_MODE} — {mode_description}\n"
        f"Allowed namespaces: {', '.join(namespaces)}\n"
        f"Data sources: Prometheus {settings.PROMETHEUS_URL}, Loki {settings.LOKI_URL}, "
        f"Tempo {settings.TEMPO_URL or '(not configured)'}\n"
        f"Environment: {settings.APP_ENV}"
    )


@tool
def current_time() -> str:
    """The current time in UTC.

    Use when you need to compute time spans, e.g. how long ago a pod restarted,
    or which time range to fetch logs for.
    """
    now = datetime.now(UTC)
    return f"{now.isoformat(timespec='seconds')} (UTC)"


# ---------------------------------------------------------------------------
# Traces (Grafana Tempo) — requests of apps running ON the cluster
# ---------------------------------------------------------------------------
#
# Namespace restriction: when K8S_ALLOWED_NAMESPACES is set, searches are
# filtered to those namespaces and a trace is only shown for its spans inside
# them. Spans with no namespace attribute count as OUTSIDE — an unlabelled
# span can't be proven to be allowed.


def _allowed_namespaces() -> list[str]:
    return list(get_settings().K8S_ALLOWED_NAMESPACES or [])


@tool
async def list_traced_services() -> str:
    """List the services on the cluster that have sent traces to Tempo.

    Use first when the user names an app loosely ("the checkout service") and
    you need the exact service name for search_traces.
    """
    try:
        services = await tempo.list_services()
    except tempo.TempoError as exc:
        return str(exc)
    if not services:
        return (
            "Tempo has no traces yet. Apps on the cluster must be instrumented "
            "(Beyla or OpenTelemetry) and send traces through Alloy."
        )
    return "Services with traces: " + ", ".join(services)


@tool
async def search_traces(
    service: str | None = None,
    namespace: str | None = None,
    only_errors: bool = False,
    min_duration_ms: int | None = None,
    since_minutes: int = 60,
    limit: int = 10,
) -> str:
    """Find recent request traces of apps on the cluster (from Grafana Tempo).

    Use to investigate slow or failing requests: e.g. only_errors=True to find
    failing requests of a service, or min_duration_ms=1000 to find slow ones.
    Returns trace ids; call get_trace on one to see where the time or the error is.

    Args:
        service: exact service name (see list_traced_services). Omit for all.
        namespace: Kubernetes namespace. Omit for all allowed namespaces.
        only_errors: only traces containing a failed span.
        min_duration_ms: only traces with a span slower than this.
        since_minutes: how far back to look, 1–1440 (default 60).
        limit: max traces to return, 1–20 (default 10).
    """
    allowed = _allowed_namespaces()
    if namespace and allowed and namespace not in allowed:
        return f"Namespace {namespace!r} is not in the allowed list ({', '.join(allowed)})."
    namespaces = [namespace] if namespace else allowed or None
    since_minutes = min(max(since_minutes, 1), 1440)
    limit = min(max(limit, 1), 20)

    try:
        query = tempo.build_query(
            service=service,
            namespaces=namespaces,
            only_errors=only_errors,
            min_duration_ms=min_duration_ms,
        )
        hits = await tempo.search_traces(query, since_seconds=since_minutes * 60, limit=limit)
    except (tempo.TempoError, ValueError) as exc:
        return str(exc)

    if not hits:
        return f"No traces matched {query} in the last {since_minutes} minutes."
    lines = [f"{len(hits)} trace(s) matching {query}, last {since_minutes} min, newest first:"]
    for h in sorted(hits, key=lambda h: -h.start_ns):
        when = datetime.fromtimestamp(h.start_ns / 1e9, UTC).strftime("%H:%M:%S UTC")
        lines.append(
            f"- {h.trace_id} at {when}: {h.root_service} {h.root_name!r}, "
            f"{h.duration_ms} ms, {h.matched_spans} matching span(s)"
        )
    return "\n".join(lines)


@tool
async def get_trace(trace_id: str) -> str:
    """Explain one request trace: the slowest path, which spans failed and why,
    and how much time each service spent.

    Use after search_traces, or when the user or a log line gives a trace id.
    """
    try:
        spans = await tempo.get_trace(trace_id)
    except (tempo.TempoError, ValueError) as exc:
        return str(exc)
    if spans is None:
        return f"Tempo has no trace with id {trace_id} (it may have expired)."

    allowed = _allowed_namespaces()
    if allowed:
        visible = [s for s in spans if s.namespace in allowed]
        if not visible:
            return (
                f"Trace {trace_id} has no spans in the allowed namespaces "
                f"({', '.join(allowed)}), so it can't be shown."
            )
        hidden = len(spans) - len(visible)
        summary = tempo.summarize_trace(trace_id, visible)
        if hidden:
            summary += f"\n({hidden} span(s) outside the allowed namespaces were left out.)"
        return summary
    return tempo.summarize_trace(trace_id, spans)


# The order in this list is also the order the model sees.
CHAT_TOOLS: list[BaseTool] = [
    system_info,
    current_time,
    list_traced_services,
    search_traces,
    get_trace,
]


def get_tools() -> list[BaseTool]:
    """The tool list for one chat turn.

    Returns a copy so callers can add/remove tools without affecting the
    original list.
    """
    return list(CHAT_TOOLS)


__all__ = ["CHAT_TOOLS", "get_tools"]
