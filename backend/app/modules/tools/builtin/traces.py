"""Built-in tools: request traces of apps on the cluster (Grafana Tempo).

Not the AI's own traces — those are in Langfuse. See
app/integrations/tempo/client.py for the two rules: TraceQL is built from
checked fields, and traces are summarised before the model sees them.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations.tempo import client as tempo
from app.modules.tools.guard import allowed_namespaces
from app.modules.tools.schema import Category, Danger, ToolSpec

# ---------------------------------------------------------------------------
# Traces (Grafana Tempo) — requests of apps running ON the cluster
# ---------------------------------------------------------------------------
#
# Namespace restriction: when K8S_ALLOWED_NAMESPACES is set, searches are
# filtered to those namespaces and a trace is only shown for its spans inside
# them. Spans with no namespace attribute count as OUTSIDE — an unlabelled
# span can't be proven to be allowed.


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


@tool(parse_docstring=True)
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
    allowed = allowed_namespaces()
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

    allowed = allowed_namespaces()
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


def _unavailable() -> str | None:
    return None if get_settings().TEMPO_URL.strip() else "TEMPO_URL is empty in .env."


TOOLS = [
    ToolSpec(
        list_traced_services,
        "Traced services",
        Category.TRACES,
        Danger.READ,
        unavailable=_unavailable,
    ),
    ToolSpec(
        search_traces, "Search traces", Category.TRACES, Danger.READ, unavailable=_unavailable
    ),
    ToolSpec(get_trace, "Explain trace", Category.TRACES, Danger.READ, unavailable=_unavailable),
]
