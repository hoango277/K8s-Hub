"""Grafana Tempo HTTP API client - READS traces of apps on the target cluster.

Role: evidence source for the assistant's trace tools and for RCA
(app/modules/rca/collectors/traces.py). NOT the AI's own traces — those are in
Langfuse (app/modules/observability/).

Traces reach Tempo from the cluster, not from this app: Beyla/OpenTelemetry
instrument the apps, Alloy forwards OTLP to Tempo, and this module only reads.

Two design rules:

  1. NO RAW TraceQL from the model. `build_query()` assembles TraceQL from
     discrete, validated fields — the same rule as "no run_kubectl(cmd)" in
     nl_command/tools.py. A value that doesn't match a strict pattern is
     rejected, so the model can't inject operators into the query.
  2. NEVER hand a raw trace to the model. A real trace has hundreds to
     thousands of spans; dumped as JSON it floods the context window and buries
     the answer. `summarize_trace()` reduces it to what diagnosis needs: the
     slowest path, the failing spans with their messages, and where the time
     went per service.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT = 10.0

# Kubernetes names and OpenTelemetry service names: letters, digits, . _ - /
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,127}$")
# Namespaces are DNS-1123 labels: no regex metacharacters can appear, so a
# list of them can go straight into a TraceQL =~ alternation.
_NAMESPACE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")
# Tempo returns ids as 32 hex chars (sometimes without leading zeros).
_TRACE_ID = re.compile(r"^[0-9a-fA-F]{1,32}$")


class TempoError(RuntimeError):
    """Tempo is not configured, unreachable, or returned an error. The message
    is written to be shown to the model/user as-is."""


def _base_url() -> str:
    url = get_settings().TEMPO_URL.strip().rstrip("/")
    if not url:
        raise TempoError(
            "No trace source is configured (TEMPO_URL is empty in .env), so traces "
            "can't be looked up."
        )
    return url


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{_base_url()}{path}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise TempoError(f"Could not reach Tempo at {_base_url()}: {type(exc).__name__}") from exc
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        # Tempo puts TraceQL parse errors in the body; they are safe and useful.
        raise TempoError(f"Tempo returned HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def _check(name: str, value: str) -> str:
    if not _SAFE_VALUE.match(value):
        raise ValueError(f"Invalid {name}: {value!r}. Use letters, digits, '.', '_', '-', '/'.")
    return value


def build_query(
    *,
    service: str | None = None,
    namespaces: list[str] | None = None,
    only_errors: bool = False,
    min_duration_ms: int | None = None,
) -> str:
    """TraceQL from discrete fields. Every value is validated, never spliced raw."""
    conds: list[str] = []
    if service:
        conds.append(f'resource.service.name = "{_check("service", service)}"')
    if namespaces:
        for n in namespaces:
            if not _NAMESPACE.match(n):
                raise ValueError(f"Invalid namespace: {n!r}.")
        if len(namespaces) == 1:
            conds.append(f'resource.k8s.namespace.name = "{namespaces[0]}"')
        else:
            alternation = "|".join(namespaces)
            conds.append(f'resource.k8s.namespace.name =~ "{alternation}"')
    if only_errors:
        conds.append("status = error")
    if min_duration_ms is not None:
        conds.append(f"duration > {int(min_duration_ms)}ms")
    return "{ " + " && ".join(conds) + " }" if conds else "{ }"


@dataclass
class TraceHit:
    trace_id: str
    root_service: str
    root_name: str
    start_ns: int
    duration_ms: int
    matched_spans: int


async def search_traces(query: str, *, since_seconds: int, limit: int) -> list[TraceHit]:
    end = int(time.time())
    data = await _get(
        "/api/search",
        {"q": query, "start": end - since_seconds, "end": end, "limit": limit},
    )
    hits: list[TraceHit] = []
    for t in (data or {}).get("traces") or []:
        matched = sum(
            int(s.get("matched") or len(s.get("spans") or [])) for s in t.get("spanSets") or []
        )
        hits.append(
            TraceHit(
                trace_id=str(t.get("traceID", "")),
                root_service=str(t.get("rootServiceName") or "?"),
                root_name=str(t.get("rootTraceName") or "?"),
                start_ns=int(t.get("startTimeUnixNano") or 0),
                duration_ms=int(t.get("durationMs") or 0),
                matched_spans=matched,
            )
        )
    return hits


async def list_services() -> list[str]:
    data = await _get("/api/v2/search/tag/resource.service.name/values")
    values = (data or {}).get("tagValues") or []
    return sorted(str(v.get("value")) for v in values if v.get("value"))


# ---------------------------------------------------------------------------
# One trace: fetch + normalise + summarise
# ---------------------------------------------------------------------------


@dataclass
class Span:
    span_id: str
    parent_id: str
    service: str
    namespace: str | None
    name: str
    kind: str
    start_ns: int
    end_ns: int
    error: bool
    error_message: str | None
    children: list[Span] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        return max(0, self.end_ns - self.start_ns) / 1e6


def _attr_value(v: dict[str, Any]) -> Any:
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in v:
            return v[key]
    return None


def _attrs(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    return {a.get("key"): _attr_value(a.get("value") or {}) for a in items or []}


def _is_error(status: dict[str, Any] | None) -> bool:
    code = (status or {}).get("code")
    return code in (2, "STATUS_CODE_ERROR", "2")


def parse_spans(payload: dict[str, Any]) -> list[Span]:
    """Flatten Tempo's OTLP JSON (v2 `{"trace": {...}}` or v1 `{"batches": [...]}`)."""
    root = payload.get("trace", payload)
    batches = root.get("resourceSpans") or root.get("batches") or []
    spans: list[Span] = []
    for batch in batches:
        res = _attrs((batch.get("resource") or {}).get("attributes"))
        service = str(res.get("service.name") or "unknown")
        namespace = res.get("k8s.namespace.name")
        for scope in batch.get("scopeSpans") or batch.get("instrumentationLibrarySpans") or []:
            for s in scope.get("spans") or []:
                message = (s.get("status") or {}).get("message") or None
                for ev in s.get("events") or []:
                    if ev.get("name") == "exception":
                        ea = _attrs(ev.get("attributes"))
                        parts = (ea.get("exception.type"), ea.get("exception.message"))
                        message = message or " ".join(str(x) for x in parts if x)
                attrs = _attrs(s.get("attributes"))
                http_status = attrs.get("http.response.status_code") or attrs.get(
                    "http.status_code"
                )
                error = _is_error(s.get("status"))
                if error and not message and http_status:
                    message = f"HTTP {http_status}"
                spans.append(
                    Span(
                        span_id=str(s.get("spanId", "")),
                        parent_id=str(s.get("parentSpanId") or ""),
                        service=service,
                        namespace=str(namespace) if namespace else None,
                        name=str(s.get("name") or "?"),
                        kind=str(s.get("kind", "")).replace("SPAN_KIND_", "").lower(),
                        start_ns=int(s.get("startTimeUnixNano") or 0),
                        end_ns=int(s.get("endTimeUnixNano") or 0),
                        error=error,
                        error_message=message,
                    )
                )
    return spans


async def get_trace(trace_id: str) -> list[Span] | None:
    """Spans of one trace, or None if Tempo doesn't have it."""
    if not _TRACE_ID.match(trace_id):
        raise ValueError(f"Invalid trace id: {trace_id!r}. Expected up to 32 hex characters.")
    data = await _get(f"/api/v2/traces/{trace_id}")
    if data is None:
        return None
    return parse_spans(data)


def _self_time_ms(span: Span) -> float:
    """Time spent in this span itself, not in its children (overlaps merged)."""
    intervals = sorted(
        (max(c.start_ns, span.start_ns), min(c.end_ns, span.end_ns)) for c in span.children
    )
    covered, cur_start, cur_end = 0, None, None
    for a, b in intervals:
        if b <= a:
            continue
        if cur_end is None or a > cur_end:
            if cur_end is not None:
                covered += cur_end - cur_start
            cur_start, cur_end = a, b
        else:
            cur_end = max(cur_end, b)
    if cur_end is not None:
        covered += cur_end - cur_start
    return max(0, (span.end_ns - span.start_ns) - covered) / 1e6


def summarize_trace(trace_id: str, spans: list[Span], *, max_items: int = 5) -> str:
    """A compact, model-readable account of one trace."""
    if not spans:
        return f"Trace {trace_id} has no spans."

    by_id = {s.span_id: s for s in spans}
    roots: list[Span] = []
    for s in spans:
        parent = by_id.get(s.parent_id) if s.parent_id else None
        if parent is not None and parent is not s:
            parent.children.append(s)
        else:
            roots.append(s)
    start = min(s.start_ns for s in spans)
    end = max(s.end_ns for s in spans)
    root = max(roots, key=lambda s: s.duration_ms)

    services = sorted({s.service for s in spans})
    namespaces = sorted({s.namespace for s in spans if s.namespace})
    errors = [s for s in spans if s.error]

    lines = [
        f"Trace {trace_id}: {root.service} {root.name!r}, {(end - start) / 1e6:.1f} ms total, "
        f"{len(spans)} spans across {len(services)} services ({', '.join(services)})"
        + (f", namespaces: {', '.join(namespaces)}" if namespaces else "")
        + ("." if not errors else f". {len(errors)} span(s) FAILED."),
    ]

    # Critical path: from the root, keep following the child that ends last —
    # that chain is what the caller actually waited for.
    path, node = [root], root
    while node.children:
        node = max(node.children, key=lambda c: c.end_ns)
        path.append(node)
    lines.append("Slowest path (what the request waited on):")
    for depth, s in enumerate(path[:12]):
        mark = "  ERROR" if s.error else ""
        lines.append(f"{'  ' * (depth + 1)}- {s.service}: {s.name} — {s.duration_ms:.1f} ms{mark}")
    if len(path) > 12:
        lines.append(f"  … {len(path) - 12} more levels")

    if errors:
        lines.append("Failed spans:")
        # Deepest failures first: the innermost error is usually the cause, the
        # outer ones just propagate it.
        depth_of = {s.span_id: 0 for s in spans}
        for s in spans:
            d, p = 0, by_id.get(s.parent_id)
            while p is not None and d < 64:
                d, p = d + 1, by_id.get(p.parent_id)
            depth_of[s.span_id] = d
        for s in sorted(errors, key=lambda e: -depth_of[e.span_id])[:max_items]:
            why = s.error_message or "status error, no message"
            lines.append(f"  - {s.service}: {s.name} — {why}")

    time_by_service: dict[str, float] = {}
    for s in spans:
        time_by_service[s.service] = time_by_service.get(s.service, 0) + _self_time_ms(s)
    total = sum(time_by_service.values()) or 1
    lines.append("Time spent per service (excluding waits on other spans):")
    for svc, ms in sorted(time_by_service.items(), key=lambda kv: -kv[1])[:max_items]:
        lines.append(f"  - {svc}: {ms:.1f} ms ({ms / total:.0%})")

    return "\n".join(lines)


async def check() -> dict[str, Any]:
    """For the Settings > Connections panel."""
    data = await _get("/api/status/buildinfo")
    return {"version": (data or {}).get("version")}


__all__ = [
    "Span",
    "TempoError",
    "TraceHit",
    "build_query",
    "check",
    "get_trace",
    "list_services",
    "parse_spans",
    "search_traces",
    "summarize_trace",
]
