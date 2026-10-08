"""Node health and capacity: not ready, under pressure, cordoned, full.

"Full" means requests, not usage: the scheduler places pods by what they
REQUEST, so a node at 98% requested CPU refuses new pods while sitting idle —
the usual reason for FailedScheduling on lab1's single node.
"""

from __future__ import annotations

from app.integrations.prometheus import client as prom
from app.modules.rca.detectors import Context, Found, kevent_evidence, meta, parse_time
from app.modules.rca.model import Entity

SATURATED_SHARE = 0.95
_PRESSURE = ("MemoryPressure", "DiskPressure", "PIDPressure")
_REQUESTED = (
    'sum by (node) (kube_pod_container_resource_requests{{resource="{res}"}})'
    ' / sum by (node) (kube_node_status_allocatable{{resource="{res}"}})'
)


def _conditions(ctx: Context, found: Found) -> None:
    for node in ctx.snap.nodes:
        name = meta(node)["name"]
        n = Entity("Node", None, name)
        conds = {c.get("type"): c for c in (node.get("status") or {}).get("conditions") or []}
        ready = conds.get("Ready", {})
        if ready and ready.get("status") != "True":
            at = parse_time(ready.get("lastTransitionTime")) or ctx.end
            found.add(
                "NodeNotReady",
                n,
                at,
                f"Node {name} is not ready",
                severity="critical",
                evidence=[("k8s", f"Ready={ready.get('status')}: {ready.get('message', '')}", at)],
            )
        for type_ in _PRESSURE:
            c = conds.get(type_, {})
            if c.get("status") == "True":
                at = parse_time(c.get("lastTransitionTime")) or ctx.end
                found.add(
                    "NodePressure",
                    n,
                    at,
                    f"Node {name} reports {type_}",
                    severity="critical",
                    evidence=[
                        ("k8s", f"{type_}=True since {at:%H:%M}: {c.get('message', '')}", at)
                    ],
                    pressure=type_,
                )
        if (node.get("spec") or {}).get("unschedulable"):
            taint = next(
                (
                    t
                    for t in (node.get("spec") or {}).get("taints") or []
                    if t.get("key") == "node.kubernetes.io/unschedulable"
                ),
                {},
            )
            at = parse_time(taint.get("timeAdded"))
            if at is None or ctx.in_window(at):
                found.add(
                    "NodeCordon",
                    n,
                    at or ctx.start,
                    f"Node {name} is cordoned",
                    severity="info",
                    evidence=[("k8s", f"spec.unschedulable=true (since {at or 'unknown'})", at)],
                )


def _node_events(ctx: Context, found: Found) -> None:
    mapping = {
        "NodeNotReady": "NodeNotReady",
        "NodeHasInsufficientMemory": "NodePressure",
        "NodeHasDiskPressure": "NodePressure",
        "NodeHasInsufficientPID": "NodePressure",
        "EvictionThresholdMet": "NodePressure",
        "NodeNotSchedulable": "NodeCordon",
    }
    grouped: dict[tuple[str, str], list] = {}
    for e in ctx.kevents:
        if e.kind == "Node" and e.reason in mapping:
            grouped.setdefault((e.name, mapping[e.reason]), []).append(e)
    for (name, type_), events in grouped.items():
        found.add(
            type_,
            Entity("Node", None, name),
            ctx.since(events),
            f"Node {name}: {events[-1].reason}",
            severity="info" if type_ == "NodeCordon" else "critical",
            evidence=kevent_evidence(events),
        )


async def _saturation(ctx: Context, found: Found) -> None:
    for res in ("cpu", "memory"):
        try:
            rows = await prom.query(_REQUESTED.format(res=res), at=ctx.end.timestamp())
        except prom.PrometheusError as exc:
            ctx.warnings.append(f"Node capacity unknown (Prometheus): {exc}")
            return
        for row in rows:
            name = (row.get("metric") or {}).get("node")
            share = float(row["value"][1])
            if name and share >= SATURATED_SHARE:
                found.add(
                    "NodeSaturated",
                    Entity("Node", None, name),
                    ctx.start,  # a state, not a moment: it held for the whole window
                    f"Node {name} has {share:.0%} of its {res} already requested",
                    evidence=[
                        (
                            "prometheus",
                            f"{res} requests / allocatable on {name} = {share:.0%}",
                            ctx.end,
                        )
                    ],
                    **{f"{res}_requested": round(share, 3)},
                )


async def detect(ctx: Context, found: Found) -> None:
    _conditions(ctx, found)
    _node_events(ctx, found)
    await _saturation(ctx, found)


__all__ = ["SATURATED_SHARE", "detect"]
