"""Error-log anomalies per pod, the NEW error templates, and who a failing pod talks to.

1. One LogQL metric query counts error-looking lines per pod over the window,
   for every namespace in scope (Loki does the counting; no lines move).
2. Pods whose count steps up (change-point, else a burst) get up to MAX_LINES
   error lines fetched — from the window AND from BASELINE_HOURS before it —
   and grouped by Drain3 into templates ("connection refused to <*>:<*>").
   Templates that first appear after the change are what changed: those
   become the evidence. A longer baseline than "the start of the window"
   keeps an hourly cron's errors from looking new.
3. Host names in those error lines ("dial tcp pg-rw.database.svc:5432:
   connect: connection refused") become "calls" edges with source `log` —
   the dependency a failing pod is failing to reach. Crash-looping pods are
   read too, even when they log too little to count as a spike.

Raw lines never leave this module.
"""

from __future__ import annotations

from collections import Counter

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from app.integrations.loki import client as loki
from app.modules.rca.detectors import (
    Context,
    Found,
    change_point,
    from_unix,
    hhmm,
    series_values,
    spike,
)
from app.modules.rca.topology import candidate_hosts
from app.modules.tools.builtin.logs import ERROR_PATTERN

MAX_PODS = 5
MAX_LINES = 300
MAX_TEMPLATES = 3
MIN_LINES_PER_STEP = 5
BASELINE_HOURS = 6
MAX_CRASHING_PODS = 5

# Lines that SAY they are info/debug are dropped even when they contain the
# word "error" in a field (Grafana logs `ErrorCode:` at level=info constantly).
_NOT_INFO = "!~ `(?i)level=(info|debug|trace)`"
_COUNT = (
    'sum by (namespace, pod) (count_over_time({{namespace=~"{ns}"}} |~ `{rx}` '
    + _NOT_INFO
    + " [{step}s]))"
)
_LINES = '{{namespace="{ns}", pod="{pod}"}} |~ `{rx}` ' + _NOT_INFO


def _miner() -> TemplateMiner:
    config = TemplateMinerConfig()
    config.profiling_enabled = False
    config.drain_sim_th = 0.5
    config.drain_depth = 4
    return TemplateMiner(config=config)


def new_templates(lines: list[tuple[float, str]], since: float) -> list[tuple[str, int]]:
    """Templates first seen at/after `since` (unix s), most frequent first.

    Lines are fed oldest first, so a template's cluster is created by its
    earliest line; clusters created before `since` were already "normal".
    """
    miner = _miner()
    born_after: set[int] = set()
    counts: Counter[int] = Counter()
    for ts, text in sorted(lines):
        result = miner.add_log_message(text[:1000])
        cid = result["cluster_id"]
        if result["change_type"] == "cluster_created" and ts >= since:
            born_after.add(cid)
        counts[cid] += 1
    templates = {c.cluster_id: c.get_template() for c in miner.drain.clusters}
    ranked = sorted(born_after, key=lambda c: -counts[c])
    return [(templates[c], counts[c]) for c in ranked if c in templates]


def dependencies_from_lines(ctx: Context, namespace: str, pod_name: str, lines: list[str]) -> int:
    """Add `log` dependency edges for Services named in the pod's error lines."""
    pod = ctx.topo.ensure_pod(namespace, pod_name)
    owner = ctx.topo.pod_owner(pod)
    if owner is None:
        return 0
    added = 0
    for line in lines:
        for host in candidate_hosts(line[:2000]):
            svc = ctx.topo.resolve_host(host, namespace)
            if svc is not None and ctx.topo.add_dependency(owner, svc, "log"):
                added += 1
    return added


async def _lines(ctx: Context, ns: str, pod: str, minutes: int, end: float) -> list[loki.LogLine]:
    return await loki.query_range(
        _LINES.format(ns=ns, pod=pod, rx=ERROR_PATTERN), minutes=minutes, limit=MAX_LINES, end=end
    )


async def _spikes(ctx: Context, found: Found) -> set[tuple[str, str]]:
    step = max(60, ctx.minutes * 60 // 60)
    series = await loki.metric_range(
        _COUNT.format(ns=ctx.namespace_regex(), rx=ERROR_PATTERN, step=step),
        minutes=ctx.minutes,
        step_seconds=step,
        end=ctx.end.timestamp(),
    )
    hits = []
    for s in series:
        labels = s.get("metric") or {}
        ns, pod = labels.get("namespace", ""), labels.get("pod")
        points = series_values(s)
        hit = None
        if pod:
            hit = change_point(points, min_absolute=MIN_LINES_PER_STEP) or spike(
                points, min_absolute=MIN_LINES_PER_STEP
            )
        if hit:
            hits.append((ns, pod, points, hit))
    hits.sort(key=lambda x: -x[3][2])

    done: set[tuple[str, str]] = set()
    baseline_end = ctx.start.timestamp()
    for ns, pod_name, points, (i, base, value) in hits[:MAX_PODS]:
        at = from_unix(points[i][0])
        evidence = [
            (
                "loki",
                f"{ns}/{pod_name}: {value:.0f} error lines per {step}s from {hhmm(at)}, "
                f"before {base:.0f}",
                at,
            )
        ]
        templates: list[tuple[str, int]] = []
        try:
            window = await _lines(ctx, ns, pod_name, ctx.minutes, ctx.end.timestamp())
            history = await _lines(ctx, ns, pod_name, BASELINE_HOURS * 60, baseline_end)
            lines = [(ln.ts_ns / 1e9, ln.line) for ln in [*history, *window]]
            templates = new_templates(lines, points[i][0])
            dependencies_from_lines(ctx, ns, pod_name, [ln.line for ln in window])
        except loki.LokiError as exc:
            ctx.warnings.append(f"Log lines of {ns}/{pod_name} unavailable: {exc}")
        for template, count in templates[:MAX_TEMPLATES]:
            evidence.append(("loki", f"new error ×{count}: {template}", None))
        found.add(
            "LogErrorSpike",
            ctx.topo.ensure_pod(ns, pod_name),
            at,
            f"Error logs on {pod_name} jumped to {value:.0f} per {step}s (before {base:.0f})",
            evidence=evidence,
            templates=[t for t, _ in templates[:MAX_TEMPLATES]],
        )
        done.add((ns, pod_name))
    return done


async def _crashing_pods(ctx: Context, found: Found, done: set[tuple[str, str]]) -> None:
    """Who crash-looping pods fail to reach: often the root cause sits there."""
    crashing = [
        e.entity
        for e in found.all()
        if e.type in ("CrashLoop", "RestartSpike") and e.entity.kind == "Pod"
    ]
    for pod in crashing[:MAX_CRASHING_PODS]:
        key = (pod.namespace or "", pod.name)
        if key in done:
            continue
        try:
            window = await _lines(ctx, key[0], pod.name, ctx.minutes, ctx.end.timestamp())
        except loki.LokiError:
            continue
        dependencies_from_lines(ctx, key[0], pod.name, [ln.line for ln in window])


async def detect(ctx: Context, found: Found) -> None:
    try:
        done = await _spikes(ctx, found)
        await _crashing_pods(ctx, found, done)
    except loki.LokiError as exc:
        ctx.warnings.append(f"Logs unavailable (Loki): {exc}")


__all__ = ["dependencies_from_lines", "detect", "new_templates"]
