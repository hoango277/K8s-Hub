"""Errors that cross a service boundary, and "who calls whom", from Tempo — across namespaces.

A few traces of the window are fetched (errors first, then a small normal
sample) and read span by span:
  - a parent span in service A with a child span in service B is a "calls"
    edge A → B (source `trace`), even when A and B live in different
    namespaces: each span carries its own `k8s.namespace.name`;
  - an error span in B under a parent in A is a DownstreamErrors event ON B
    (the callee): rules then let it explain an ErrorRateSpike on A.

Only services that match a workload of the cluster count (Beyla names a
service after its Deployment); Tempo also holds traces of things RCA can't
act on.
"""

from __future__ import annotations

from collections import defaultdict

from app.integrations.tempo import client as tempo
from app.modules.rca.detectors import Context, Found, from_unix, hhmm
from app.modules.rca.model import Entity

MAX_ERROR_TRACES = 8
MAX_SAMPLE_TRACES = 4


async def _spans(ctx: Context, only_errors: bool, limit: int) -> list[list[tempo.Span]]:
    namespaces = ctx.scope if ctx.namespaces is not None else None
    query = tempo.build_query(namespaces=namespaces, only_errors=only_errors)
    hits = await tempo.search_traces(
        query,
        since_seconds=int((ctx.end - ctx.start).total_seconds()),
        limit=limit,
        end=ctx.end.timestamp(),
    )
    out = []
    for hit in hits[:limit]:
        spans = await tempo.get_trace(hit.trace_id)
        if spans:
            out.append(spans)
    return out


def _workload_of(ctx: Context, span: tempo.Span) -> Entity | None:
    """The workload a span's service runs as, in the span's own namespace."""
    for key in ctx.topo.template_labels:
        w = ctx.topo.entities[key]
        if w.name == span.service and (span.namespace is None or w.namespace == span.namespace):
            return w
    return None


async def detect(ctx: Context, found: Found) -> None:
    try:
        traces = await _spans(ctx, True, MAX_ERROR_TRACES)
        traces += await _spans(ctx, False, MAX_SAMPLE_TRACES)
    except (tempo.TempoError, ValueError) as exc:
        ctx.warnings.append(f"Traces unavailable (Tempo): {exc}")
        return

    errors: dict[str, list[tuple[Entity, tempo.Span]]] = defaultdict(list)
    callees: dict[str, Entity] = {}
    for spans in traces:
        by_id = {s.span_id: s for s in spans}
        for s in spans:
            parent = by_id.get(s.parent_id)
            if parent is None or (parent.service, parent.namespace) == (s.service, s.namespace):
                continue
            caller, callee = _workload_of(ctx, parent), _workload_of(ctx, s)
            if caller is None or callee is None:
                continue
            ctx.topo.add_dependency(caller, callee, "trace")
            if s.error and ctx.in_scope(callee.namespace):
                errors[callee.key].append((caller, s))
                callees[callee.key] = callee

    for key, items in errors.items():
        callee = callees[key]
        first = min(s.start_ns for _, s in items)
        at = from_unix(first / 1e9)
        callers = sorted({c.label() for c, _ in items})
        messages = sorted({s.error_message or s.name for _, s in items})
        found.add(
            "DownstreamErrors",
            callee,
            at,
            f"Calls from {', '.join(callers)} to {callee.name} failed ({len(items)} spans)",
            evidence=[
                (
                    "tempo",
                    f"{len(items)} failed span(s) in {callee.label()} called by "
                    f"{', '.join(callers)}, first at {hhmm(at)}",
                    at,
                ),
                *[("tempo", f"{callee.name}: {m}", None) for m in messages[:2]],
            ],
            callers=callers,
        )


__all__ = ["detect"]
