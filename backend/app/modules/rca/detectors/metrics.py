"""Resource and request-level anomalies from Prometheus, for every namespace in scope.

A handful of queries per run, whatever the number of pods or namespaces
(`namespace=~"a|b"`):
  MemoryNearLimit  working set ≥ 90% of the memory limit (the step before OOMKilled);
  MemoryLeak       working set rising steadily, on course to hit the limit soon;
  CpuThrottling    ≥ 25% of CFS periods throttled;
  ErrorRateSpike   5xx share of requests steps up (Beyla server metrics);
  LatencySpike     p95 latency steps up (Beyla server metrics).

Request anomalies use a change-point test (where the level steps up, not
"above the first 30%"), then a SEASONAL check: the same hours yesterday. A
nightly batch that is slow every night at 02:00 is normal for that service,
and blaming it would bury the real cause.

The event time is the FIRST sample over the line, not the peak — ordering in
time is what lets rules say "memory filled up, then the container died".
"""

from __future__ import annotations

import statistics

from app.integrations.prometheus import client as prom
from app.modules.rca.detectors import (
    Context,
    Found,
    change_point,
    first_at_or_above,
    from_unix,
    hhmm,
    linear_trend,
    series_values,
    spike,
)
from app.modules.rca.topology import workload

MEMORY_SHARE = 0.9
THROTTLE_SHARE = 0.25
# MemoryLeak: a steady climb (r² ≥ 0.8) already past 60% of the limit that,
# continued, reaches the limit within this many seconds.
LEAK_MIN_LEVEL = 0.6
LEAK_MIN_R2 = 0.8
LEAK_HORIZON = 2 * 3600
SEASONAL_FACTOR = 1.5
DAY = 86400
MAX_SERIES = 200

_SEL = 'namespace=~"{ns}", container!="", container!="POD"'
_BY = "(namespace, pod, container)"
_MEMORY = (
    # max_over_time per step: a container OOM-killed every 30 s lives between
    # two samples, so plain samples miss exactly the peaks that matter.
    f"max by {_BY} (max_over_time("
    f"container_memory_working_set_bytes{{{_SEL}}}[{{step}}s]))"
    f" / on {_BY} max by {_BY} "
    '(kube_pod_container_resource_limits{namespace=~"{ns}", resource="memory"})'
)
_THROTTLE = (
    f"sum by {_BY} (rate(container_cpu_cfs_throttled_periods_total{{{_SEL}}}[5m]))"
    f" / sum by {_BY} (rate(container_cpu_cfs_periods_total{{{_SEL}}}[5m]))"
)
_BEYLA = 'http_server_request_duration_seconds{suffix}{{k8s_namespace_name=~"{ns}"{extra}}}'
_WL = "(k8s_namespace_name, k8s_deployment_name)"
_ERRORS = (
    f"sum by {_WL} (rate("
    + _BEYLA.format(suffix="_count", ns="{ns}", extra=', http_response_status_code=~"5.."')
    + f"[2m])) / sum by {_WL} (rate("
    + _BEYLA.format(suffix="_count", ns="{ns}", extra="")
    + "[2m]))"
)
_LATENCY = (
    "histogram_quantile(0.95, sum by (k8s_namespace_name, k8s_deployment_name, le) (rate("
    + _BEYLA.format(suffix="_bucket", ns="{ns}", extra="")
    + "[2m])))"
)


def _step(ctx: Context) -> int:
    return max(15, ctx.minutes * 60 // 120)


async def _range(ctx: Context, template: str, *, shift: int = 0) -> list[dict]:
    query = template.replace("{ns}", ctx.namespace_regex()).replace("{step}", str(_step(ctx)))
    series = await prom.query_range(
        query, minutes=ctx.minutes, step_seconds=_step(ctx), end=ctx.end.timestamp() - shift
    )
    return series[:MAX_SERIES]


async def _resources(ctx: Context, found: Found) -> None:
    for template, type_, line, label in (
        (_MEMORY, "MemoryNearLimit", MEMORY_SHARE, "memory working set / limit"),
        (_THROTTLE, "CpuThrottling", THROTTLE_SHARE, "CPU periods throttled"),
    ):
        for s in await _range(ctx, template):
            labels = s.get("metric") or {}
            ns, pod_name = labels.get("namespace", ""), labels.get("pod", "?")
            container = labels.get("container", "?")
            points = series_values(s)
            if not points:
                continue
            pod = ctx.topo.ensure_pod(ns, pod_name)
            i = first_at_or_above(points, line)
            if i is not None:
                at = from_unix(points[i][0])
                peak = max(v for _, v in points)
                found.add(
                    type_, pod, at, f"{container}: {label} reached {peak:.0%}",
                    evidence=[("prometheus", f"{pod_name}/{container}: {label} first ≥ "
                               f"{line:.0%} at {hhmm(at)}, peak {peak:.0%}", at)],
                    container=container, peak=round(peak, 3),
                )  # fmt: skip
            elif type_ == "MemoryNearLimit":
                _leak(found, pod, container, points)


def _leak(found: Found, pod, container: str, points: list[tuple[float, float]]) -> None:
    """Memory climbing steadily toward the limit, before it gets there."""
    slope, r2 = linear_trend(points)
    last_t, last = points[-1]
    if slope <= 0 or r2 < LEAK_MIN_R2 or last < LEAK_MIN_LEVEL:
        return
    eta = (1.0 - last) / slope  # seconds until the limit at this rate
    if eta > LEAK_HORIZON:
        return
    at = from_unix(points[0][0])
    growth = slope * 3600
    found.add(
        "MemoryLeak", pod, at,
        f"{container}: memory rising {growth:.0%} of the limit per hour, now {last:.0%}",
        evidence=[("prometheus", f"{pod.name}/{container}: working set {last:.0%} of limit, "
                   f"+{growth:.0%}/h (r²={r2:.2f}); limit reached in ~{eta / 60:.0f} min "
                   "at this rate", from_unix(last_t))],
        container=container, growth_per_hour=round(growth, 3), r2=round(r2, 2),
    )  # fmt: skip


def _step_up(points: list[tuple[float, float]], **kw: float) -> tuple[int, float, float] | None:
    """A sustained step up (change-point), else a short burst (spike)."""
    return change_point(points, **kw) or spike(points, **kw)


def _yesterday(series: list[dict]) -> dict[tuple[str, str], list[tuple[float, float]]]:
    out = {}
    for s in series:
        m = s.get("metric") or {}
        out[(m.get("k8s_namespace_name", ""), m.get("k8s_deployment_name", ""))] = series_values(s)
    return out


async def _requests(ctx: Context, found: Found) -> None:
    # (what, number format): "p95 latency 0.29s (baseline 0.02s)".
    for template, type_, kwargs, (what, fmt) in (
        (_ERRORS, "ErrorRateSpike", {"min_absolute": 0.05}, ("5xx share", "{:.0%}")),
        (_LATENCY, "LatencySpike", {"min_ratio": 2.0, "min_absolute": 0.2},
         ("p95 latency", "{:.2f}s")),
    ):  # fmt: skip
        today = await _range(ctx, template)
        if not today:
            continue
        yesterday = _yesterday(await _range(ctx, template, shift=DAY))
        for s in today:
            m = s.get("metric") or {}
            ns, name = m.get("k8s_namespace_name", ""), m.get("k8s_deployment_name")
            points = series_values(s)
            hit = _step_up(points, **kwargs) if name else None
            if hit is None:
                continue
            i, base, value = hit
            usual = [v for _, v in yesterday.get((ns, name), [])[i:]]
            if usual and value <= SEASONAL_FACTOR * statistics.median(usual):
                continue  # as high as at the same time yesterday: the daily pattern
            at = from_unix(points[i][0])
            seasonal = (
                f", yesterday at this time {fmt.format(statistics.median(usual))}" if usual else ""
            )
            found.add(
                type_, workload(ns, name), at,  # type: ignore[arg-type]
                f"{name}: {what} {fmt.format(value)} (baseline {fmt.format(base)})",
                evidence=[("prometheus", f"{ns}/{name}: {what} {fmt.format(value)} from "
                           f"{hhmm(at)}, before {fmt.format(base)}{seasonal} (Beyla)", at)],
                value=round(value, 4), baseline=round(base, 4),
            )  # fmt: skip


async def detect(ctx: Context, found: Found) -> None:
    try:
        await _resources(ctx, found)
        await _requests(ctx, found)
    except prom.PrometheusError as exc:
        ctx.warnings.append(f"Metrics unavailable (Prometheus): {exc}")


__all__ = ["MEMORY_SHARE", "THROTTLE_SHARE", "detect"]
