"""Built-in tool: container metrics from Prometheus, from fixed PromQL templates.

The model picks a metric by NAME; it never writes PromQL. Free-form PromQL
would let it read any series (including namespaces outside the allowed list)
and hand back raw matrices that flood the context. Templates keep both in check.

Metric names are the cAdvisor / kube-state-metrics series that
kube-prometheus-stack ships by default (as on lab1).
"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.tools import tool

from app.core.config import get_settings
from app.integrations.prometheus import client as prom
from app.modules.tools.guard import ToolInputError, check_namespace, clamp
from app.modules.tools.schema import Category, Danger, ToolSpec

# A pod name PREFIX (a deployment's pods share it). No dots: "." is a regex
# metacharacter in the =~ matcher and pod names almost never contain one.
_POD_PREFIX = re.compile(r"^[a-z0-9]([-a-z0-9]{0,62})?$")

Metric = Literal["cpu", "memory", "restarts", "throttling"]

_SEL = 'namespace="{ns}", pod=~"^{pod}.*", container!="", container!="POD"'
_BY = "sum by (pod, container)"
QUERIES: dict[str, str] = {
    "cpu": f"{_BY} (rate(container_cpu_usage_seconds_total{{{_SEL}}}[5m]))",
    "memory": f"{_BY} (container_memory_working_set_bytes{{{_SEL}}})",
    "restarts": (
        f'{_BY} (kube_pod_container_status_restarts_total{{namespace="{{ns}}", pod=~"^{{pod}}.*"}})'
    ),
    "throttling": (
        f"{_BY} (rate(container_cpu_cfs_throttled_periods_total{{{_SEL}}}[5m]))"
        f" / {_BY} (rate(container_cpu_cfs_periods_total{{{_SEL}}}[5m]))"
    ),
}
LIMITS = (
    f"{_BY} (kube_pod_container_resource_limits"
    '{namespace="{ns}", pod=~"^{pod}.*", resource="{res}"})'
)


def _fmt(metric: str, value: float) -> str:
    if metric == "cpu":
        return f"{value * 1000:.0f}m"
    if metric == "memory":
        return f"{value / 2**20:.0f}Mi"
    if metric == "throttling":
        return f"{value:.0%}"
    return f"{value:.0f}"


def _fill(template: str, ns: str, pod: str, res: str = "") -> str:
    return template.replace("{ns}", ns).replace("{pod}", pod).replace("{res}", res)


@tool(parse_docstring=True)
async def pod_metrics(namespace: str, pod: str, metric: Metric, range_minutes: int = 60) -> str:
    """CPU, memory, restarts or CPU throttling of a workload's containers over time.

    Use to check resource pressure: memory close to its limit before an
    OOMKilled, CPU throttling behind slowness, or restarts climbing.

    Args:
        namespace: Kubernetes namespace.
        pod: pod name or name prefix (a deployment name matches all its pods).
        metric: one of cpu, memory, restarts, throttling.
        range_minutes: time window, 5–1440 (default 60).
    """
    try:
        check_namespace(namespace)
        if not _POD_PREFIX.match(pod):
            raise ToolInputError(f"Invalid pod name or prefix: {pod!r}.")
        if metric not in QUERIES:
            raise ToolInputError(
                f"Unknown metric {metric!r}. Use cpu, memory, restarts or throttling."
            )
        minutes = clamp(range_minutes, 5, 1440)
        step = max(15, minutes * 60 // 60)
        series = await prom.query_range(
            _fill(QUERIES[metric], namespace, pod), minutes=minutes, step_seconds=step
        )
        limits: dict[tuple[str, str], float] = {}
        if metric in ("cpu", "memory"):
            for s in await prom.query(_fill(LIMITS, namespace, pod, metric)):
                key = (s["metric"].get("pod", ""), s["metric"].get("container", ""))
                limits[key] = float(s["value"][1])
    except (ToolInputError, prom.PrometheusError) as exc:
        return str(exc)

    if not series:
        return (
            f"No {metric} data for pods matching {namespace}/{pod}* in the last {minutes} minutes."
        )

    lines = [f"{metric} for {namespace}/{pod}*, last {minutes} min ({len(series)} container(s)):"]
    for s in series[:15]:
        vals = [float(v) for _, v in s.get("values") or [] if v not in ("NaN", "+Inf", "-Inf")]
        if not vals:
            continue
        labels = s.get("metric") or {}
        who = f"{labels.get('pod', '?')}/{labels.get('container', '?')}"
        if metric == "restarts":
            lines.append(f"- {who}: {vals[-1]:.0f} total, +{vals[-1] - vals[0]:.0f} in the window")
            continue
        now, low, high = (_fmt(metric, v) for v in (vals[-1], min(vals), max(vals)))
        row = f"- {who}: now {now}, min {low}, max {high}"
        limit = limits.get((labels.get("pod", ""), labels.get("container", "")))
        if limit:
            row += f", limit {_fmt(metric, limit)} (peak {max(vals) / limit:.0%} of limit)"
        elif metric in ("cpu", "memory"):
            row += ", no limit set"
        lines.append(row)
    if len(series) > 15:
        lines.append(f"… {len(series) - 15} more containers not shown")
    return "\n".join(lines)


def _unavailable() -> str | None:
    return None if get_settings().PROMETHEUS_URL.strip() else "PROMETHEUS_URL is empty in .env."


TOOLS = [
    ToolSpec(pod_metrics, "Pod metrics", Category.METRICS, Danger.READ, unavailable=_unavailable)
]
