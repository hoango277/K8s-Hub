"""Run an APPROVED plan, exactly as stored.

Called only by approval_service after a human (or auto mode) decided. The
plan is not rebuilt: rebuilding would ask the cluster again and could run
something different from what the approver read. Ops run in order; on the
first failure the rest are skipped and the result says which already ran,
because Kubernetes has no multi-object transaction to roll back.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from app.integrations.k8s import resources as res
from app.modules.nl_command.planner import ActionPlan
from app.modules.sandbox import SandboxError, run_command

MAX_OUTPUT = 6000

# A recorded object larger than this is not kept (a big ConfigMap): the change
# still runs, it just can't be reverted automatically.
SNAPSHOT_MAX_BYTES = 256_000
# Server bookkeeping that must not travel back into a restore or a re-create.
_SERVER_FIELDS = (
    "uid", "resourceVersion", "creationTimestamp", "generation", "managedFields",
    "selfLink", "deletionTimestamp", "deletionGracePeriodSeconds",
)  # fmt: skip
_CONTROLLER_ANNOTATIONS = ("deployment.kubernetes.io/revision",)


def restorable(obj: dict[str, Any]) -> dict[str, Any]:
    """The object as a client would write it back: no status, no server bookkeeping."""
    obj = copy.deepcopy(obj)
    obj.pop("status", None)
    meta = obj.get("metadata") or {}
    for key in _SERVER_FIELDS:
        meta.pop(key, None)
    annotations = meta.get("annotations") or {}
    for key in _CONTROLLER_ANNOTATIONS:
        annotations.pop(key, None)
    if "annotations" in meta and not annotations:
        meta.pop("annotations")
    return obj


async def snapshot(plan: ActionPlan) -> list[dict[str, Any]] | None:
    """Every object of a REST plan as it is right now, before the plan runs.

    Stored in approvals.before_state; a revert rebuilds the earlier state from it
    (revert.py). None for commands and MCP calls: K8s-Hub can't know what they
    touch. A Secret is never read — plans can't target one (resolve_kind refuses),
    and this checks again rather than trust that.
    """
    if plan.mcp or plan.argv or not plan.ops:
        return None
    out: list[dict[str, Any]] = []
    for op in plan.ops:
        entry: dict[str, Any] = {
            "kind": op.kind,
            "name": op.name,
            "namespace": op.namespace,
            "path": op.read_path or op.path,
        }
        if res.is_blocked(op.kind):
            entry["skipped"] = "secret"
            out.append(entry)
            continue
        status, data = await res.request("GET", entry["path"])
        if status == 404:
            entry["existed"] = False
        elif status >= 400:
            entry["error"] = str(res.api_error(status, data, f"{op.kind} {op.name}"))
        else:
            entry["existed"] = True
            obj = restorable(data)
            if len(json.dumps(obj)) > SNAPSHOT_MAX_BYTES:
                entry["too_large"] = True
            else:
                entry["object"] = obj
        out.append(entry)
    return out


async def record_after(entries: list[dict[str, Any]]) -> None:
    """Each object's version right after the change, in place: lets a later revert
    tell whether someone changed it since (generation for objects that have one —
    status updates bump resourceVersion all the time — resourceVersion otherwise)."""
    for entry in entries:
        if entry.get("skipped"):
            continue
        status, data = await res.request("GET", entry["path"])
        if status >= 400:
            entry["after"] = None  # gone (a delete)
            continue
        meta = data.get("metadata") or {}
        entry["after"] = {
            "resourceVersion": meta.get("resourceVersion"),
            "generation": meta.get("generation"),
        }


async def _execute_mcp(call: dict) -> tuple[bool, str]:
    from app.modules.tools import mcp_client
    from app.services import tool_service

    try:
        token = await tool_service.server_token(call["server_id"])
        out = await mcp_client.call_tool(call["url"], call["tool"], call["args"], token)
    except (mcp_client.McpError, LookupError) as exc:
        return False, str(exc)
    return True, out[:MAX_OUTPUT]


async def execute(plan: ActionPlan) -> tuple[bool, str]:
    """(ok, human-readable result)."""
    if plan.mcp:
        return await _execute_mcp(plan.mcp)
    if plan.argv:
        try:
            result = await run_command(plan.argv, time_limit=plan.time_limit)
        except SandboxError as exc:
            return False, str(exc)
        status = "exit 0" if result.ok else (
            "timed out" if result.timed_out else f"exit {result.exit_code}"
        )
        return result.ok, f"$ {' '.join(plan.argv)}\n({status})\n{result.text(MAX_OUTPUT)}"

    lines: list[str] = []
    for i, op in enumerate(plan.ops):
        label = f"{op.kind} {op.namespace + '/' if op.namespace else ''}{op.name}"
        try:
            status, data = await res.request(
                op.method, op.path, query=list(op.query), body=op.body, content_type=op.content_type
            )
        except res.K8sError as exc:
            status, data = 0, {"message": str(exc)}
        if status == 0 or status >= 400:
            error = str(res.api_error(status, data, label)) if status else data["message"]
            lines.append(f"✗ {label}: {error}")
            skipped = len(plan.ops) - i - 1
            if skipped:
                lines.append(f"{skipped} remaining object(s) were NOT changed.")
            return False, "\n".join(lines)
        verb = {"DELETE": "deleted", "PATCH": "updated", "PUT": "restored"}.get(op.method, "done")
        if op.content_type == "application/apply-patch+yaml":
            verb = "applied"
        lines.append(f"✓ {label} {verb}")
    return True, "\n".join(lines)


__all__ = ["SNAPSHOT_MAX_BYTES", "execute", "record_after", "restorable", "snapshot"]
