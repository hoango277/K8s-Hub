"""Who calls whom, from metrics: Beyla's CLIENT-side metrics in Prometheus.

Beyla (eBPF, in Alloy) records each outgoing request of an instrumented pod:
`http_client_request_duration_seconds_count` and
`db_client_operation_duration_seconds_count`, labelled with the CALLER
(`k8s_namespace_name`, `k8s_deployment_name`/`_statefulset_name`/
`_daemonset_name`) and the CALLEE's address (`server_address`). The address
is resolved like a host name in configuration (Topology.resolve_host), so a
call to `pg-rw.database.svc.cluster.local` becomes a `metric` edge to that
Service — and to the workloads behind it.

Run BEFORE the scope is decided (pipeline): these edges are what pulls a
dependency's namespace into the analysis. Two queries, cluster-wide.
No event is produced here — only topology.
"""

from __future__ import annotations

from datetime import datetime

from app.integrations.prometheus import client as prom
from app.modules.rca.topology import Topology, workload

_OWNER_LABELS = (
    ("k8s_deployment_name", "Deployment"),
    ("k8s_statefulset_name", "StatefulSet"),
    ("k8s_daemonset_name", "DaemonSet"),
)
_BY = (
    "k8s_namespace_name, k8s_deployment_name, k8s_statefulset_name, k8s_daemonset_name, "
    "server_address"
)
METRICS = (
    "http_client_request_duration_seconds_count",
    "db_client_operation_duration_seconds_count",
)


def add_metric_dependencies(topo: Topology, rows: list[dict]) -> int:
    added = 0
    for row in rows:
        m = row.get("metric") or {}
        ns, address = m.get("k8s_namespace_name"), m.get("server_address")
        if not ns or not address:
            continue
        caller = next(
            (workload(ns, m[label], kind) for label, kind in _OWNER_LABELS if m.get(label)), None
        )
        if caller is None or caller.key not in topo.entities:
            continue
        svc = topo.resolve_host(address, ns, by_prefix=True)
        if svc is not None and topo.add_dependency(caller, svc, "metric"):
            added += 1
    return added


async def discover(topo: Topology, end: datetime, minutes: int) -> str | None:
    """Add `metric` edges seen in the window; returns a warning, or None."""
    for metric in METRICS:
        query = f"sum by ({_BY}) (increase({metric}[{minutes}m])) > 0"
        try:
            rows = await prom.query(query, at=end.timestamp())
        except prom.PrometheusError as exc:
            return f"Service calls from metrics unavailable (Prometheus): {exc}"
        add_metric_dependencies(topo, rows)
    return None


__all__ = ["METRICS", "add_metric_dependencies", "discover"]
