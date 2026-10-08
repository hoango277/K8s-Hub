"""Controller-level symptoms: replicas missing, rollouts stuck, services with
no ready backend, volume claims pending, autoscalers capped.

These are what an operator (or an alert) usually notices first; the pod and
change detectors then supply what can explain them.
"""

from __future__ import annotations

from typing import Any

from app.modules.rca.detectors import Context, Found, hhmm, kevent_evidence, meta, parse_time
from app.modules.rca.model import Entity
from app.modules.rca.topology import workload

_ENDPOINTS_CHANGED = "endpoints.kubernetes.io/last-change-trigger-time"


def _condition(obj: dict[str, Any], type_: str) -> dict[str, Any]:
    conds = (obj.get("status") or {}).get("conditions") or []
    return next((c for c in conds if c.get("type") == type_), {})


def _deployments(ctx: Context, found: Found) -> None:
    for d in ctx.objects("deployments"):
        name = meta(d)["name"]
        w = workload(meta(d).get("namespace") or "", name, "Deployment")
        spec, status = d.get("spec") or {}, d.get("status") or {}
        want = int(spec.get("replicas", 1) or 0)
        available = int(status.get("availableReplicas") or 0)
        progressing = _condition(d, "Progressing")
        if progressing.get("reason") == "ProgressDeadlineExceeded":
            at = parse_time(progressing.get("lastTransitionTime")) or ctx.end
            found.add(
                "RolloutStuck",
                w,
                at,
                f"Rollout of {name} exceeded its progress deadline",
                severity="critical",
                evidence=[
                    (
                        "k8s",
                        "Progressing=False ProgressDeadlineExceeded: "
                        + str(progressing.get("message", "")),
                        at,
                    )
                ],
            )
        if want > available:
            cond = _condition(d, "Available")
            at = (
                parse_time(cond.get("lastTransitionTime"))
                if cond.get("status") == "False"
                else None
            )
            found.add(
                "ReplicasUnavailable",
                w,
                at or ctx.end,
                f"{name}: {available}/{want} replicas available",
                severity="critical" if available == 0 else "warning",
                evidence=[
                    (
                        "k8s",
                        f"Deployment {name}: desired {want}, available {available}, "
                        f"updated {status.get('updatedReplicas', 0)}",
                        at,
                    )
                ],
                desired=want,
                available=available,
            )


def _other_workloads(ctx: Context, found: Found) -> None:
    for kind, items, want_key, ready_key in (
        ("StatefulSet", ctx.objects("statefulsets"), "replicas", "readyReplicas"),
        ("DaemonSet", ctx.objects("daemonsets"), "desiredNumberScheduled", "numberReady"),
    ):
        for obj in items:
            name = meta(obj)["name"]
            status = obj.get("status") or {}
            want = int(
                (obj.get("spec") or {}).get(want_key, 1)
                if kind == "StatefulSet"
                else status.get(want_key) or 0
            )
            ready = int(status.get(ready_key) or 0)
            if want > ready:
                # No controller condition carries a time here; the pods' own
                # events will be earlier anyway, so "end of window" is harmless.
                found.add(
                    "ReplicasUnavailable",
                    workload(meta(obj).get("namespace") or "", name, kind),
                    ctx.end,
                    f"{name}: {ready}/{want} replicas ready",
                    severity="critical" if ready == 0 else "warning",
                    evidence=[("k8s", f"{kind} {name}: desired {want}, ready {ready}", None)],
                    desired=want,
                    available=ready,
                )


def _services(ctx: Context, found: Found) -> None:
    endpoints = {(meta(e).get("namespace"), meta(e)["name"]): e for e in ctx.snap.endpoints}
    for svc in ctx.objects("services"):
        name = meta(svc)["name"]
        if not (svc.get("spec") or {}).get("selector"):
            continue  # ExternalName / manually managed endpoints
        ep = endpoints.get((meta(svc).get("namespace"), name), {})
        subsets = ep.get("subsets") or []
        ready = sum(len(s.get("addresses") or []) for s in subsets)
        not_ready = sum(len(s.get("notReadyAddresses") or []) for s in subsets)
        if ready:
            continue
        changed = parse_time((meta(ep).get("annotations") or {}).get(_ENDPOINTS_CHANGED))
        entity = Entity("Service", meta(svc).get("namespace"), name)
        # A Service that never had a backend and nobody calls is idle by design
        # (seen on lab1: CloudNativePG's read-only `pg-ro` with a single
        # instance). It is a symptom when something stands behind it, something
        # depends on it, or its endpoints just changed.
        backed = ctx.topo.related(entity, "backend_workloads") or ctx.topo.related(
            entity, "service_callers"
        )
        if not backed and not not_ready and not ctx.in_window(changed):
            continue
        at = changed or ctx.end
        found.add(
            "ServiceNoEndpoints",
            entity,
            at,
            f"Service {name} has no ready endpoints ({not_ready} not ready)",
            severity="critical",
            evidence=[
                (
                    "k8s",
                    f"Endpoints {name}: 0 ready, {not_ready} not ready, last change {hhmm(at)}",
                    at,
                )
            ],
            not_ready=not_ready,
        )


def _pvcs(ctx: Context, found: Found) -> None:
    for pvc in ctx.objects("pvcs"):
        name = meta(pvc)["name"]
        if (pvc.get("status") or {}).get("phase") != "Pending":
            continue
        events = ctx.kevents_for(
            "PersistentVolumeClaim", name, namespace=meta(pvc).get("namespace")
        )
        at = parse_time(meta(pvc).get("creationTimestamp")) or ctx.end
        sc = (pvc.get("spec") or {}).get("storageClassName")
        found.add(
            "PvcPending",
            Entity("PVC", meta(pvc).get("namespace"), name),
            at,
            f"Volume claim {name} is pending (storage class {sc or 'default'})",
            severity="critical",
            evidence=[
                ("k8s", f"PVC {name}: Pending since {hhmm(at)}, storageClassName={sc}", at),
                *kevent_evidence(events),
            ],
            storage_class=sc,
        )


def _hpas(ctx: Context, found: Found) -> None:
    for hpa in ctx.objects("hpas"):
        spec, status = hpa.get("spec") or {}, hpa.get("status") or {}
        current, top = status.get("currentReplicas"), spec.get("maxReplicas")
        if current is None or top is None or int(current) < int(top):
            continue
        limited = _condition(hpa, "ScalingLimited")
        at = parse_time(limited.get("lastTransitionTime")) or ctx.end
        found.add(
            "HpaAtMax",
            Entity("HPA", meta(hpa).get("namespace"), meta(hpa)["name"]),
            at,
            f"Autoscaler {meta(hpa)['name']} is at its maximum ({top} replicas)",
            evidence=[
                (
                    "k8s",
                    f"HPA {meta(hpa)['name']}: current {current} = max {top}; "
                    f"{limited.get('message', '')}",
                    at,
                )
            ],
        )


async def detect(ctx: Context, found: Found) -> None:
    _deployments(ctx, found)
    _other_workloads(ctx, found)
    _services(ctx, found)
    _pvcs(ctx, found)
    _hpas(ctx, found)


__all__ = ["detect"]
