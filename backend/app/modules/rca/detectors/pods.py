"""Pod and container states: what is broken now, and what broke earlier in the window.

Two sources, merged per pod:
  - the pod status in the snapshot — exact, but only for pods that still exist
    and only the CURRENT state plus the last termination;
  - Kubernetes events (API + Loki history) — the only trace of pods that were
    replaced since, and the timestamps a status doesn't keep.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.modules.rca.detectors import Context, Found, hhmm, kevent_evidence, meta, parse_time
from app.modules.rca.model import Entity

_IMAGE_PULL = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName", "ErrImageNeverPull"}
_CONFIG = {"CreateContainerConfigError", "CreateContainerError", "RunContainerError"}

# Event message → event type, for pod events whose reason alone is too vague
# ("Failed", "BackOff" cover several problems).
_MESSAGE_RULES: list[tuple[set[str], re.Pattern[str], str]] = [
    ({"BackOff", "Failed"}, re.compile(r"pull|ErrImage|image", re.I), "ImagePullError"),
    (
        {"Failed"},
        re.compile(
            r"CreateContainerConfigError|couldn't find key|not found|configmap|secret", re.I
        ),
        "ContainerConfigError",
    ),
    ({"BackOff"}, re.compile(r"restarting failed container", re.I), "CrashLoop"),
]
_REASON_TYPES = {
    "Unhealthy": "ProbeFailed",
    "FailedScheduling": "Unschedulable",
    "FailedMount": "VolumeMountFailed",
    "FailedAttachVolume": "VolumeMountFailed",
    "Evicted": "Evicted",
    "OOMKilling": "OOMKilled",
}
_SEVERITY = {
    "CrashLoop": "critical",
    "ImagePullError": "critical",
    "ContainerConfigError": "critical",
    "OOMKilled": "critical",
    "Unschedulable": "critical",
}


def _first_event_time(ctx: Context, pod: Entity, reasons: set[str]) -> datetime | None:
    events = [
        e for e in ctx.kevents_for("Pod", pod.name, namespace=pod.namespace) if e.reason in reasons
    ]
    return ctx.since(events) if events else None


def _container_states(ctx: Context, found: Found, pod_obj: dict[str, Any], pod: Entity) -> None:
    status = pod_obj.get("status") or {}
    phase = status.get("phase") or "?"
    statuses = [
        *(status.get("initContainerStatuses") or []),
        *(status.get("containerStatuses") or []),
    ]
    for cs in statuses:
        name = cs.get("name", "?")
        state = cs.get("state") or {}
        waiting = state.get("waiting") or {}
        last = (cs.get("lastState") or {}).get("terminated") or {}
        last_at = parse_time(last.get("finishedAt"))
        restarts = int(cs.get("restartCount") or 0)
        reason = waiting.get("reason")
        msg = (waiting.get("message") or "").strip()

        if last.get("reason") == "OOMKilled" and (
            ctx.in_window(last_at) or reason == "CrashLoopBackOff"
        ):
            found.add(
                "OOMKilled",
                pod,
                last_at or ctx.end,
                f"Container {name} was OOM-killed (exit {last.get('exitCode', 137)})",
                severity="critical",
                evidence=[
                    (
                        "k8s",
                        f"{name}: last terminated OOMKilled, exit code "
                        f"{last.get('exitCode', 137)} at {hhmm(last_at)}",
                        last_at,
                    )
                ],
                container=name,
            )

        if reason in _IMAGE_PULL:
            at = _first_event_time(ctx, pod, {"Failed", "BackOff"}) or parse_time(
                status.get("startTime")
            )
            images = {
                c.get("name"): c.get("image")
                for c in (pod_obj.get("spec") or {}).get("containers") or []
            }
            found.add(
                "ImagePullError",
                pod,
                at or ctx.end,
                f"Container {name} can't pull image {images.get(name, '?')}",
                severity="critical",
                evidence=[("k8s", f"{name}: {reason}: {msg}", None)],
                container=name,
                image=images.get(name),
            )
        elif reason in _CONFIG:
            at = _first_event_time(ctx, pod, {"Failed"}) or parse_time(status.get("startTime"))
            found.add(
                "ContainerConfigError",
                pod,
                at or ctx.end,
                f"Container {name} can't start: {reason}",
                severity="critical",
                evidence=[("k8s", f"{name}: {reason}: {msg}", None)],
                container=name,
            )
        elif reason == "CrashLoopBackOff":
            at = _first_event_time(ctx, pod, {"BackOff"}) or last_at or ctx.end
            exit_info = (
                f"last exit {last.get('reason', '?')} (code {last.get('exitCode', '?')})"
                f" at {hhmm(last_at)}"
                if last
                else "no termination recorded"
            )
            found.add(
                "CrashLoop",
                pod,
                at,
                f"Container {name} is crash-looping ({restarts} restarts)",
                severity="critical",
                evidence=[
                    ("k8s", f"{name}: CrashLoopBackOff, {restarts} restarts, {exit_info}", last_at)
                ],
                container=name,
                restarts=restarts,
                exit_code=last.get("exitCode"),
                exit_reason=last.get("reason"),
            )
        elif restarts and ctx.in_window(last_at) and last.get("reason") != "OOMKilled":
            found.add(
                "RestartSpike",
                pod,
                last_at,  # type: ignore[arg-type]
                f"Container {name} restarted "
                f"(exit {last.get('reason', '?')}, code {last.get('exitCode', '?')})",
                evidence=[
                    (
                        "k8s",
                        f"{name}: {restarts} restarts, last at {hhmm(last_at)} "
                        f"({last.get('reason', '?')}, exit {last.get('exitCode', '?')})",
                        last_at,
                    )
                ],
                container=name,
                restarts=restarts,
                exit_code=last.get("exitCode"),
            )

        if phase == "Running" and state.get("running") and not cs.get("ready"):
            ready_cond = next(
                (c for c in status.get("conditions") or [] if c.get("type") == "Ready"), {}
            )
            at = parse_time(ready_cond.get("lastTransitionTime")) or ctx.end
            found.add(
                "PodNotReady",
                pod,
                at,
                f"Container {name} is running but not ready",
                evidence=[("k8s", f"{name}: running, ready=false since {hhmm(at)}", at)],
                container=name,
            )

    if status.get("reason") == "Evicted":
        found.add(
            "Evicted",
            pod,
            parse_time(status.get("startTime")) or ctx.end,
            "Pod was evicted",
            evidence=[("k8s", f"Evicted: {status.get('message', '')}", None)],
        )
    if phase == "Pending":
        sched = next(
            (c for c in status.get("conditions") or [] if c.get("type") == "PodScheduled"), {}
        )
        if sched.get("status") == "False":
            at = parse_time(sched.get("lastTransitionTime")) or ctx.end
            found.add(
                "Unschedulable",
                pod,
                at,
                "Pod can't be scheduled on any node",
                severity="critical",
                evidence=[
                    (
                        "k8s",
                        f"{sched.get('reason', 'Unschedulable')}: {sched.get('message', '')}",
                        at,
                    )
                ],
                message=sched.get("message", ""),
            )


def _from_events(ctx: Context, found: Found) -> None:
    by_pod: dict[tuple[str, str], list] = {}
    for e in ctx.kevents:
        if e.kind != "Pod" or e.type != "Warning" or not ctx.in_scope(e.namespace):
            continue
        type_ = _REASON_TYPES.get(e.reason)
        if type_ is None:
            type_ = next(
                (
                    t
                    for reasons, rx, t in _MESSAGE_RULES
                    if e.reason in reasons and rx.search(e.message)
                ),
                None,
            )
        if type_ == "ProbeFailed" and not re.search(r"probe", e.message, re.I):
            type_ = None
        if type_:
            by_pod.setdefault((e.namespace or "", e.name, type_), []).append(e)

    for (ns, name, type_), events in by_pod.items():
        pod = ctx.topo.ensure_pod(ns, name)
        first = ctx.since(events)
        total = sum(e.count for e in events)
        attrs: dict[str, Any] = {}
        summary = f"{events[-1].reason} on pod {name} ({total}×)"
        if type_ == "ProbeFailed":
            kind = re.search(r"(Readiness|Liveness|Startup) probe", events[-1].message, re.I)
            attrs["probe"] = kind.group(1).lower() if kind else None
            probe = (attrs["probe"] or "health").capitalize()
            summary = f"{probe} probe failing on pod {name} ({total}×)"
        elif type_ == "Unschedulable":
            attrs["message"] = events[-1].message
            summary = f"Pod {name} can't be scheduled"
        found.add(
            type_,
            pod,
            first,
            summary,
            severity=_SEVERITY.get(type_, "warning"),  # type: ignore[arg-type]
            evidence=kevent_evidence(events),
            **attrs,
        )


async def detect(ctx: Context, found: Found) -> None:
    for pod_obj in ctx.objects("pods"):
        m = meta(pod_obj)
        pod = ctx.topo.ensure_pod(m.get("namespace") or "", m.get("name", "?"))
        _container_states(ctx, found, pod_obj, pod)
    _from_events(ctx, found)


__all__ = ["detect"]
