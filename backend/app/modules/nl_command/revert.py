"""Undo an executed change with a reverse PROPOSAL (docs/ke-hoach/hoan-tac-thay-doi.md).

A revert is not an "undo" button that runs: it builds the plan that takes the
objects back to how they were just before the change (approvals.before_state,
recorded at execution by executor.snapshot) and hands it to the normal flow —
guardrails, server dry-run, diff, a human decision, verification. What runs is
still exactly the plan the approver read.

| change      | revert                                                          |
|-------------|-----------------------------------------------------------------|
| scale       | scale back to the replica count before (planner.plan_scale)    |
| set_image   | put the previous image back on that container                   |
| apply       | delete what it created; restore what it changed (PUT of the     |
|             | earlier version with the CURRENT resourceVersion: if someone   |
|             | edits the object before the revert runs, it fails with 409      |
|             | instead of silently overwriting them)                           |
| delete      | create the object again (server-side apply of the earlier one)  |
| delete_pod  | same, for a bare pod; a controller-owned pod was replaced      |
| restart, command, mcp, a deleted namespace: can't be reverted (blocker) |
"""

from __future__ import annotations

import copy
from typing import Any

from app.db.models.approval import Approval
from app.integrations.k8s import resources as res
from app.modules.nl_command import planner
from app.modules.nl_command.executor import restorable
from app.modules.nl_command.guardrails import check_write_namespace, danger_of_kind
from app.modules.nl_command.planner import FIELD_MANAGER, ActionPlan, K8sOp
from app.modules.tools.guard import ToolInputError, check_name

REVERTIBLE = ("scale", "set_image", "apply", "delete", "delete_pod")


class RevertError(ValueError):
    """The change can't (or needn't) be reverted. Message is user-facing."""


def ref(row: Approval) -> str:
    return f"#{str(row.id)[:8]}"


def blocker(row: Approval) -> str | None:
    """Why this change can't be reverted — decided from the row alone, no cluster
    call, so the API can say it for every card in a list. None = worth trying
    (plan_revert may still find there is nothing left to undo)."""
    if row.status != "executed":
        return "Only a change that ran successfully can be reverted."
    if row.kind == "restart":
        return "A rolling restart can't be undone: the pods were already replaced."
    if row.kind == "command":
        return "K8s-Hub can't tell what a command changed, so it can't undo it."
    if row.kind == "mcp":
        return "K8s-Hub can't tell what an external tool changed, so it can't undo it."
    if row.kind not in REVERTIBLE:
        return "K8s-Hub doesn't know how to undo this kind of change."
    snaps: list[dict[str, Any]] = row.before_state or []
    if not snaps:
        return (
            "This change ran before K8s-Hub recorded the previous state, so it can't be undone "
            "automatically."
        )
    if any(s.get("error") or s.get("skipped") for s in snaps):
        return "K8s-Hub couldn't record the state before this change ran."
    if any(s.get("too_large") for s in snaps):
        return (
            "The previous state was too large to keep, so this change can't be undone "
            "automatically."
        )
    first = snaps[0]
    if row.kind in ("scale", "set_image", "delete", "delete_pod") and not first.get("existed"):
        return "The object didn't exist when the change ran: there is nothing to restore."
    meta = (first.get("object") or {}).get("metadata") or {}
    if row.kind == "delete_pod" and meta.get("ownerReferences"):
        return "The pod's controller already created a replacement: there is nothing to undo."
    if row.kind == "delete" and first.get("kind") == "Namespace":
        return (
            "Deleting a namespace removed everything in it; recreating it empty would not undo "
            "that."
        )
    return None


def changed_since(snap: dict[str, Any], current: dict[str, Any] | None) -> bool:
    """Was the object edited after the change ran? Generation when the object has
    one (status updates bump resourceVersion constantly), resourceVersion otherwise."""
    after = snap.get("after")
    if not after or current is None:
        return False
    meta = current.get("metadata") or {}
    if after.get("generation") is not None and meta.get("generation") is not None:
        return meta["generation"] != after["generation"]
    return meta.get("resourceVersion") != after.get("resourceVersion")


def _label(kind: str, namespace: str | None, name: str) -> str:
    return f"{kind.lower()} {namespace}/{name}" if namespace else f"{kind.lower()} {name}"


async def _current(snap: dict[str, Any]) -> dict[str, Any] | None:
    status, data = await res.request("GET", snap["path"])
    if status == 404:
        return None
    if status >= 400:
        raise RevertError(str(res.api_error(status, data, f"{snap['kind']} {snap['name']}")))
    return data


async def _object_op(obj: dict[str, Any], method: str, path: str | None = None) -> K8sOp:
    """A PUT (restore) or a server-side apply (create) of `obj`, checked like
    planner.plan_apply checks a manifest: kind (never a Secret), name,
    allowed and unprotected namespace."""
    try:
        found = await res.resolve_kind(str(obj.get("kind") or ""))  # refuses Secrets
    except res.K8sError as exc:
        raise RevertError(str(exc)) from exc
    rkind = res.Kind(found.kind, found.plural, str(obj.get("apiVersion")), found.namespaced)
    meta = obj.setdefault("metadata", {})
    name = str(meta.get("name") or "")
    try:
        check_name(rkind.kind, name)
        namespace = (
            check_write_namespace(str(meta.get("namespace") or "default"))
            if rkind.namespaced
            else None
        )
    except ToolInputError as exc:
        raise RevertError(str(exc)) from exc
    if method == "PUT":
        target = path or rkind.path(namespace, name)
        return K8sOp("PUT", target, rkind.kind, name, namespace, body=obj)
    return K8sOp(
        "PATCH",
        rkind.path(namespace, name),
        rkind.kind,
        name,
        namespace,
        body=obj,
        content_type="application/apply-patch+yaml",
        query=[["fieldManager", FIELD_MANAGER]],
    )


def _for_recreate(obj: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The earlier object, made fit to be created again."""
    obj = copy.deepcopy(obj)
    meta = obj.setdefault("metadata", {})
    notes = []
    if meta.pop("ownerReferences", None):
        notes.append(
            "Its owner references were dropped: the old owner may be gone, and the garbage "
            "collector would delete the object again."
        )
    spec = obj.get("spec") or {}
    # A headless Service keeps clusterIP "None"; any other IP may be taken by now.
    if obj.get("kind") == "Service" and spec.get("clusterIP") not in (None, "None"):
        spec.pop("clusterIP", None)
        spec.pop("clusterIPs", None)
        notes.append("The Service gets a new cluster IP; clients using the old IP must re-resolve.")
    if obj.get("kind") == "Pod":
        spec.pop("nodeName", None)  # let the scheduler place it; the old node may be gone
    return obj, notes


async def _revert_scale(row: Approval, plan: ActionPlan, snap: dict[str, Any]) -> ActionPlan:
    op = plan.ops[0]
    before = ((snap.get("object") or {}).get("spec") or {}).get("replicas", 1)
    current = await _current(snap)
    if current is None:
        raise RevertError(f"{op.kind} {op.namespace}/{op.name} no longer exists.")
    now = (current.get("spec") or {}).get("replicas", 1)
    if now == before:
        raise RevertError(
            f"Nothing to revert: {_label(op.kind, op.namespace, op.name)} already has {before} "
            "replica(s)."
        )
    try:
        revert = await planner.plan_scale(op.kind.lower(), op.namespace or "", op.name, before)  # type: ignore[arg-type]
    except ToolInputError as exc:
        raise RevertError(str(exc)) from exc
    if changed_since(snap, current):
        revert.notes.append(
            f"The replica count changed again after {ref(row)} (now {now}); this sets it back to "
            f"{before}, the count before {ref(row)}."
        )
    return revert


def _containers(obj: dict[str, Any]) -> list[dict[str, Any]]:
    spec = (((obj.get("spec") or {}).get("template") or {}).get("spec")) or {}
    return list(spec.get("containers") or [])


async def _revert_image(row: Approval, plan: ActionPlan, snap: dict[str, Any]) -> ActionPlan:
    op = plan.ops[0]
    changed = _containers(op.body or {})[0]
    container, new_image = changed.get("name"), changed.get("image")
    before = _containers(snap.get("object") or {})
    old = next((c.get("image") for c in before if c.get("name") == container), None)
    if not old:
        raise RevertError(f"The recorded state has no container {container!r}.")
    current = await _current(snap)
    if current is None:
        raise RevertError(f"{op.kind} {op.namespace}/{op.name} no longer exists.")
    now = next((c.get("image") for c in _containers(current) if c.get("name") == container), None)
    if now == old:
        raise RevertError(f"Nothing to revert: container {container} already runs {old}.")
    try:
        revert = await planner.plan_set_image(
            op.kind.lower(),  # type: ignore[arg-type]
            op.namespace or "",
            op.name,
            str(container),
            str(old),
        )
    except ToolInputError as exc:
        raise RevertError(str(exc)) from exc
    if now != new_image:
        revert.notes.append(
            f"The container now runs {now}, not {new_image}: it changed again after {ref(row)}. "
            f"This sets it back to {old}."
        )
    return revert


async def _recreate(row: Approval, snap: dict[str, Any]) -> ActionPlan:
    label = _label(snap["kind"], snap.get("namespace"), snap["name"])
    if await _current(snap) is not None:
        raise RevertError(f"Nothing to revert: {label} exists again.")
    obj, notes = _for_recreate(snap.get("object") or {})
    op = await _object_op(obj, "APPLY")
    return ActionPlan(
        kind="apply",
        title=f"Recreate {label} deleted by {ref(row)}",
        danger=danger_of_kind(op.kind),  # type: ignore[arg-type]
        namespace=op.namespace,
        target=f"{op.kind}/{op.name}",
        ops=[op],
        verify={"type": "reverted", "exists": [_ref_of(op)], "gone": []},
        notes=notes,
    )


def _ref_of(op: K8sOp) -> dict[str, Any]:
    return {
        "path": op.read_path or op.path,
        "kind": op.kind,
        "name": op.name,
        "namespace": op.namespace,
    }


async def _revert_apply(row: Approval, plan: ActionPlan, snaps: list[dict[str, Any]]) -> ActionPlan:
    ops: list[K8sOp] = []
    notes: list[str] = []
    restored: list[K8sOp] = []
    deleted: list[K8sOp] = []
    danger = "caution"
    # Reverse order: objects inside a namespace the change created go before it.
    for snap in reversed(snaps):
        label = _label(snap["kind"], snap.get("namespace"), snap["name"])
        current = await _current(snap)
        if not snap.get("existed"):
            if current is None:
                notes.append(f"{label} (created by {ref(row)}) is already gone.")
                continue
            op = K8sOp("DELETE", snap["path"], snap["kind"], snap["name"], snap.get("namespace"))
            if snap["kind"] == "Namespace":
                danger = "dangerous"
                notes.append(
                    f"Deletes namespace {snap['name']} and EVERYTHING in it, including whatever "
                    f"was created there after {ref(row)}."
                )
            elif danger_of_kind(snap["kind"]) == "dangerous":
                danger = "dangerous"
            if changed_since(snap, current):
                notes.append(
                    f"{label} was edited after {ref(row)} created it; deleting it drops those "
                    "edits too."
                )
            deleted.append(op)
            ops.append(op)
            continue

        before = copy.deepcopy(snap.get("object") or {})
        if current is None:
            obj, more = _for_recreate(before)
            op = await _object_op(obj, "APPLY")
            notes.append(
                f"{label} was deleted after {ref(row)}; it is created again as it was before."
            )
            notes += more
        else:
            if restorable(current) == before:
                notes.append(f"{label} is already as it was before {ref(row)}.")
                continue
            # The CURRENT version: an edit between proposal and approval makes the PUT
            # fail with 409 instead of being silently overwritten.
            current_rv = (current.get("metadata") or {}).get("resourceVersion")
            before.setdefault("metadata", {})["resourceVersion"] = current_rv
            op = await _object_op(before, "PUT", snap["path"])
            if changed_since(snap, current):
                notes.append(
                    f"{label} was edited again after {ref(row)}: restoring the version from before "
                    f"{ref(row)} also undoes those later edits. Check the diff."
                )
        restored.append(op)
        ops.append(op)

    if not ops:
        raise RevertError(
            f"Nothing to revert: every object is already as it was before {ref(row)}."
        )
    if len(ops) == 1 and restored:
        op = restored[0]
        title = f"Restore {_label(op.kind, op.namespace, op.name)} to its version before {ref(row)}"
    elif len(ops) == 1:
        op = deleted[0]
        title = f"Delete {_label(op.kind, op.namespace, op.name)} created by {ref(row)}"
    else:
        parts = []
        if restored:
            parts.append(f"restore {len(restored)} object(s)")
        if deleted:
            parts.append(f"delete {len(deleted)} it created")
        title = f"Undo {ref(row)}: {' and '.join(parts)}"
    namespaces = sorted({op.namespace for op in ops if op.namespace})
    return ActionPlan(
        kind="apply",
        title=title,
        danger=danger,  # type: ignore[arg-type]
        namespace=namespaces[0] if len(namespaces) == 1 else None,
        target=", ".join(f"{op.kind}/{op.name}" for op in ops)[:300],
        ops=ops,
        verify={
            "type": "reverted",
            "exists": [_ref_of(op) for op in restored],
            "gone": [_ref_of(op) for op in deleted],
        },
        notes=notes,
    )


async def plan_revert(row: Approval) -> ActionPlan:
    """The reverse plan of an executed change, against the cluster as it is NOW.

    Raises RevertError (user-facing) when it can't be reverted or nothing is left
    to undo. The plan still goes through approval_service.propose: dry-run, diff,
    a human decision.
    """
    reason = blocker(row)
    if reason:
        raise RevertError(reason)
    plan = ActionPlan.from_json(row.plan)
    snaps: list[dict[str, Any]] = row.before_state or []
    try:
        if row.kind == "scale":
            revert = await _revert_scale(row, plan, snaps[0])
        elif row.kind == "set_image":
            revert = await _revert_image(row, plan, snaps[0])
        elif row.kind in ("delete", "delete_pod"):
            revert = await _recreate(row, snaps[0])
        else:
            revert = await _revert_apply(row, plan, snaps)
    except res.K8sError as exc:
        raise RevertError(str(exc)) from exc
    revert.title = f"Revert: {revert.title}"[:300]
    return revert


__all__ = ["REVERTIBLE", "RevertError", "blocker", "changed_since", "plan_revert", "ref"]
