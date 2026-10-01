"""Server-side dry-run of a plan, and the diff the approver will read.

`dryRun=All` makes the API server run everything a real request would —
admission webhooks, validation, defaulting, quota — without storing the
result. A plan that fails here is refused before it reaches a human: an
approver should only ever see changes the cluster would actually accept.

Commands (custom CLI tools) get a dry-run only when the CLI has one
(kubectl `--dry-run=server`, helm `--dry-run`); otherwise the card says so and
the approver judges the command itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.integrations.k8s import resources as res
from app.integrations.k8s.diff import object_diff
from app.modules.nl_command.planner import ActionPlan, K8sOp
from app.modules.sandbox import SandboxError, run_command

MAX_OUTPUT = 6000

# Subcommands that accept a dry-run flag.
_KUBECTL_DRY_RUN = frozenset(
    {
        "apply", "create", "delete", "patch", "replace", "scale", "set", "label",
        "annotate", "expose", "autoscale", "run", "taint", "drain", "cordon",
        "uncordon", "rollout",
    }
)  # fmt: skip
_HELM_DRY_RUN = frozenset({"install", "upgrade", "uninstall", "rollback"})


@dataclass
class DryRunResult:
    ok: bool
    diff: str | None = None
    output: str | None = None
    error: str | None = None


def _label(op: K8sOp) -> str:
    return f"{op.kind} {op.namespace + '/' if op.namespace else ''}{op.name}"


async def _dry_run_op(op: K8sOp) -> tuple[str | None, str | None]:
    """(diff, error) for one REST call."""
    status, before = await res.request("GET", op.read_path or op.path)
    if status == 404:
        before_obj = None
    elif status >= 400:
        return None, str(res.api_error(status, before, _label(op)))
    else:
        before_obj = before
    if op.method in ("PATCH", "DELETE") and op.content_type != "application/apply-patch+yaml":
        if before_obj is None:
            return None, f"{_label(op)} does not exist (any more)."
    status, after = await res.request(
        op.method,
        op.path,
        query=[*op.query, ["dryRun", "All"]],
        body=op.body,
        content_type=op.content_type,
    )
    if status >= 400:
        return None, str(res.api_error(status, after, _label(op)))
    after_obj = None if op.method == "DELETE" else after
    return object_diff(before_obj, after_obj, _label(op)), None


def _command_dry_run_argv(argv: list[str]) -> list[str] | None:
    program, rest = argv[0], argv[1:]
    verb = rest[0] if rest else ""
    if program == "kubectl" and verb in _KUBECTL_DRY_RUN:
        return [*argv, "--dry-run=server"]
    if program == "helm" and verb in _HELM_DRY_RUN:
        return [*argv, "--dry-run"]
    return None


async def _dry_run_command(plan: ActionPlan) -> DryRunResult:
    assert plan.argv
    argv = _command_dry_run_argv(plan.argv)
    if argv is None:
        return DryRunResult(
            ok=True,
            output=f"{plan.argv[0]} has no dry-run for this command: review the command itself.",
        )
    try:
        result = await run_command(argv, time_limit=plan.time_limit)
    except SandboxError as exc:
        return DryRunResult(ok=False, error=str(exc))
    text = result.text(MAX_OUTPUT)
    if not result.ok and "unknown flag" in text:
        # An older CLI, or a subcommand without the flag: no dry-run, not a failure.
        return DryRunResult(
            ok=True, output=f"{plan.argv[0]} doesn't support a dry-run here: review the command."
        )
    if not result.ok:
        return DryRunResult(ok=False, error=f"The dry-run failed:\n{text}")
    return DryRunResult(ok=True, output=text)


async def dry_run(plan: ActionPlan) -> DryRunResult:
    if plan.mcp:
        # No dry-run exists for an arbitrary remote tool: the approver judges
        # the exact call, shown in place of a diff.
        call = json.dumps(plan.mcp["args"], indent=2, ensure_ascii=False, sort_keys=True)
        return DryRunResult(
            ok=True,
            diff=f"--- call\n+++ {plan.mcp['server']} / {plan.mcp['tool']}\n"
            + "".join(f"+{line}\n" for line in call.splitlines()),
            output="MCP tools have no dry-run: this is the exact call that will be made.",
        )
    if plan.argv:
        return await _dry_run_command(plan)
    diffs: list[str] = []
    notes: list[str] = []
    # Namespaces this same plan creates. A dry-run doesn't store them, so the
    # API server would answer "namespace not found" for every object meant to
    # go inside — those get a client-side diff instead of a server dry-run.
    new_namespaces: set[str] = set()
    for op in plan.ops:
        if op.namespace and op.namespace in new_namespaces:
            diffs.append(object_diff(None, op.body, _label(op)))
            notes.append(
                f"{_label(op)} can't be dry-run before its namespace exists: the server "
                "will validate it when the change runs."
            )
            continue
        try:
            diff, error = await _dry_run_op(op)
        except res.K8sError as exc:
            return DryRunResult(ok=False, error=str(exc))
        if error:
            return DryRunResult(ok=False, error=error)
        if op.kind == "Namespace" and diff and diff.startswith("--- /dev/null"):
            new_namespaces.add(op.name)
        diffs.append(diff or "")
    output = "The API server accepted the change in dry-run mode (nothing was stored)."
    return DryRunResult(ok=True, diff="\n".join(diffs), output="\n".join([output, *notes]))


__all__ = ["DryRunResult", "dry_run"]
