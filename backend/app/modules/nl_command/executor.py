"""Run an APPROVED plan, exactly as stored.

Called only by approval_service after a human (or auto mode) decided. The
plan is not rebuilt: rebuilding would ask the cluster again and could run
something different from what the approver read. Ops run in order; on the
first failure the rest are skipped and the result says which already ran,
because Kubernetes has no multi-object transaction to roll back.
"""

from __future__ import annotations

from app.integrations.k8s import resources as res
from app.modules.nl_command.planner import ActionPlan
from app.modules.sandbox import SandboxError, run_command

MAX_OUTPUT = 6000


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
        verb = {"DELETE": "deleted", "PATCH": "updated"}.get(op.method, "done")
        if op.content_type == "application/apply-patch+yaml":
            verb = "applied"
        lines.append(f"✓ {label} {verb}")
    return True, "\n".join(lines)


__all__ = ["execute"]
