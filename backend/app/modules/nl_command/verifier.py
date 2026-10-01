"""After a change ran: did the cluster actually get there?

"The API accepted the patch" is not "the service is fine": a new image can
fail to pull, a scale-up can stay Pending for lack of CPU. The verifier waits
a bounded time for the rollout to settle and reports what it saw. A rollout
still in progress when time runs out is reported as such (not as failure);
the approval page can re-check later.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.integrations.k8s import resources as res

WAIT_SECONDS = 45
POLL_SECONDS = 3


def _rollout_state(kind: str, obj: dict[str, Any]) -> tuple[bool, str]:
    spec, status = obj.get("spec") or {}, obj.get("status") or {}
    meta = obj.get("metadata") or {}
    observed = (status.get("observedGeneration") or 0) >= (meta.get("generation") or 0)
    if kind == "DaemonSet":
        want = status.get("desiredNumberScheduled") or 0
        updated = status.get("updatedNumberScheduled") or 0
        available = status.get("numberAvailable") or 0
        done = observed and updated == want and available == want
        return done, f"{updated}/{want} updated, {available}/{want} available"
    want = spec.get("replicas", 1)
    updated = status.get("updatedReplicas") or 0
    ready = status.get("availableReplicas" if kind == "Deployment" else "readyReplicas") or 0
    total = status.get("replicas") or 0
    done = observed and updated == want and ready == want and total == want
    if kind == "StatefulSet" and status.get("updateRevision"):
        done = done and status.get("currentRevision") == status.get("updateRevision")
    return done, f"{updated}/{want} updated, {ready}/{want} ready"


async def _why_not_ready(namespace: str, name: str) -> str:
    """The most recent warning about the workload's pods, if any — usually
    the actual reason (ImagePullBackOff, FailedScheduling…)."""
    try:
        events = await res.list_objects(
            await res.resolve_kind("events"), namespace, field_selector="type=Warning", limit=200
        )
    except res.K8sError:
        return ""
    related = [
        e for e in events if ((e.get("involvedObject") or {}).get("name") or "").startswith(name)
    ]
    related.sort(key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "", reverse=True)
    if not related:
        return ""
    e = related[0]
    return f" Latest warning: {e.get('reason')}: {(e.get('message') or '')[:200]}"


async def _verify_rollout(check: dict[str, Any], wait: int) -> tuple[bool, str]:
    rkind = await res.resolve_kind(check["kind"])
    loops = max(1, wait // POLL_SECONDS)
    state = ""
    for i in range(loops):
        obj = await res.get_object(rkind, check["namespace"], check["name"])
        if obj is None:
            return False, f"{check['kind']} {check['name']} no longer exists."
        done, state = _rollout_state(rkind.kind, obj)
        if done:
            return True, f"Rollout complete: {state}."
        if i < loops - 1:
            await asyncio.sleep(POLL_SECONDS)
    reason = await _why_not_ready(check["namespace"], check["name"])
    return False, f"Rollout not finished after {wait} s: {state}.{reason}"


async def _verify_deleted(check: dict[str, Any]) -> tuple[bool, str]:
    rkind = await res.resolve_kind(check["kind"])
    obj = await res.get_object(rkind, check["namespace"], check["name"])
    if obj is None:
        return True, f"{check['kind']} {check['name']} is gone."
    if (obj.get("metadata") or {}).get("deletionTimestamp"):
        return True, f"{check['kind']} {check['name']} is terminating."
    return False, f"{check['kind']} {check['name']} still exists."


async def _verify_exists(check: dict[str, Any]) -> tuple[bool, str]:
    missing = []
    for o in check.get("objects") or []:
        status, _ = await res.request("GET", o["path"])
        if status >= 400:
            missing.append(f"{o['kind']}/{o['name']}")
    if missing:
        return False, f"Not found after apply: {', '.join(missing)}."
    return True, f"{len(check.get('objects') or [])} object(s) present in the cluster."


async def verify(check: dict[str, Any] | None, *, ok: bool, wait: int = WAIT_SECONDS) -> tuple[
    bool | None, str
]:
    """(passed or None when there is nothing to check, message)."""
    if not check:
        return None, "Nothing to verify for this change."
    try:
        if check["type"] == "rollout":
            return await _verify_rollout(check, wait)
        if check["type"] == "deleted":
            return await _verify_deleted(check)
        if check["type"] == "exists":
            return await _verify_exists(check)
        if check["type"] == "call_ok":
            return ok, "The tool call succeeded." if ok else "The tool call failed."
        if check["type"] == "exit_code":
            return ok, "The command exited with 0." if ok else "The command failed."
    except res.K8sError as exc:
        return False, f"Could not verify: {exc}"
    return None, "Unknown verification type."


__all__ = ["verify"]
