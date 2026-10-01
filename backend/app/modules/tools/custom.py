"""Custom tools: a CLI wrapped as a tool, defined on the web (kubectl-ai style).

kubectl-ai describes a custom tool with four fields — name, description,
command, command_desc — and lets the model write the command line. Same
here, with the gaps kubectl-ai leaves filled in:

  - the PROGRAM is fixed by the engineer; the model only writes arguments;
  - no shell: arguments are split into argv (shlex), so `;`, `|`, `$()` are
    plain characters, never a second command;
  - read or change is decided by the engineer's `read_only_prefixes`
    (kubectl-ai marks every custom-tool call "unknown" and asks each time);
  - reads run at once in the sandbox; changes become an approval, dry-run
    first when the CLI has one (kubectl, helm);
  - interactive/streaming flags and Secrets are refused; namespaces follow
    the allowed list and the protected set, like every other tool.

What a command can reach is whatever identity the sandbox runs it with: your
kubeconfig with SANDBOX_BACKEND=local, the sandbox ServiceAccount with
SANDBOX_BACKEND=kubernetes (deploy/sandbox/sandbox.yaml).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field, create_model

from app.modules.nl_command import intent
from app.modules.nl_command.guardrails import check_write_namespace
from app.modules.nl_command.planner import plan_command
from app.modules.sandbox import SandboxError, run_command
from app.modules.tools.guard import ToolInputError, allowed_namespaces, check_namespace
from app.modules.tools.schema import Category, Danger, ToolSpec

NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
COMMAND = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_OUTPUT = 8000
# Words that make a change hard to undo: shown as "dangerous" on the card.
_DESTRUCTIVE = frozenset(
    {"delete", "drain", "uninstall", "destroy", "rm", "remove", "prune", "purge", "taint", "cordon"}
)


@dataclass
class CustomToolDef:
    name: str
    title: str
    description: str
    command: str
    usage: str = ""
    read_only_prefixes: list[str] = field(default_factory=list)
    timeout_seconds: int = 60
    enabled: bool = True


def _check_namespaces(tokens: list[str], *, write: bool) -> str | None:
    ns = intent.namespace_of(tokens)
    allowed = allowed_namespaces()
    if intent.spans_all_namespaces(tokens):
        if write:
            raise ToolInputError("A change can't target all namespaces at once (-A).")
        if allowed:
            raise ToolInputError(
                f"Only these namespaces are allowed: {', '.join(allowed)}. Use -n instead of -A."
            )
        return None
    if ns:
        return check_write_namespace(ns) if write else check_namespace(ns)
    if allowed:
        raise ToolInputError(
            f"Add -n <namespace>: only these namespaces are allowed: {', '.join(allowed)}."
        )
    return None


def _description(d: CustomToolDef) -> str:
    reads = ", ".join(f"`{p}`" for p in d.read_only_prefixes) or "none"
    return (
        f"{d.description.strip()}\n\n"
        f"Runs `{d.command} <arguments>` (no shell: pipes and redirects don't work). "
        f"Read-only subcommands run at once: {reads}. Anything else is a CHANGE: it is "
        "dry-run where possible and waits for an engineer's approval."
    )[:1024]


def _args_schema(d: CustomToolDef) -> type[BaseModel]:
    usage = d.usage.strip() or f"Arguments for {d.command}, e.g. a subcommand and its flags."
    return create_model(
        f"{d.name}_args",
        arguments=(
            str,
            Field(description=f"Arguments after `{d.command}`.\n{usage}"[:2000]),
        ),
    )


def build_spec(d: CustomToolDef) -> ToolSpec:
    async def run(arguments: str, config: RunnableConfig) -> str:
        from app.modules.tools.builtin.actions import propose

        try:
            tokens = intent.split_arguments(d.command, arguments)
            intent.check_tokens(tokens)
            kind = intent.classify(tokens, d.read_only_prefixes)
            namespace = _check_namespaces(tokens, write=kind == "write")
        except ToolInputError as exc:
            return str(exc)

        argv = [d.command, *tokens]
        if kind == "write":
            danger = "dangerous" if _DESTRUCTIVE & {t.lower() for t in tokens} else "caution"
            plan = plan_command(
                d.name, argv, namespace=namespace, time_limit=d.timeout_seconds, danger=danger
            )

            async def build():  # noqa: ANN202 - matches propose()'s callable
                return plan

            return await propose(build, source=d.name, config=config)

        try:
            result = await run_command(argv, time_limit=d.timeout_seconds)
        except SandboxError as exc:
            return str(exc)
        status = "exit 0" if result.ok else (
            "timed out" if result.timed_out else f"exit {result.exit_code}"
        )
        return f"$ {' '.join(argv)}\n({status})\n{result.text(MAX_OUTPUT)}"

    tool = StructuredTool.from_function(
        coroutine=run,
        name=d.name,
        description=_description(d),
        args_schema=_args_schema(d),
    )
    return ToolSpec(
        tool=tool,
        title=d.title,
        category=Category.CUSTOM,
        # Mixed: reads run, changes wait for approval. Shown as "write" so the
        # catalog never presents a CLI that can change things as harmless.
        danger=Danger.WRITE,
        source="custom",
    )


# Starting points offered on the Tools tab, as kubectl-ai ships tool samples.
TEMPLATES: list[CustomToolDef] = [
    CustomToolDef(
        name="kubectl",
        title="kubectl",
        description=(
            "The Kubernetes CLI, for anything the dedicated tools don't cover: rollout history, "
            "`top`, `auth can-i`, labels, patches."
        ),
        command="kubectl",
        usage=(
            "Put the verb first, flags after: `get pods -n shop -o wide`, `top pods -n shop`, "
            "`rollout history deployment/api -n shop`, `auth can-i list pods -n shop`, "
            "`label deployment/api -n shop tier=backend`. Always give -n <namespace>. "
            "No -w/--watch, no logs -f, no exec -it."
        ),
        read_only_prefixes=[
            "get", "describe", "logs", "top", "events", "explain", "api-resources",
            "api-versions", "version", "cluster-info", "rollout status", "rollout history",
            "auth can-i", "auth whoami",
        ],
    ),
    CustomToolDef(
        name="helm",
        title="Helm",
        description="Inspect and manage Helm releases: what is installed, which values, history.",
        command="helm",
        usage=(
            "`list -n monitoring`, `status kps -n monitoring`, `history kps -n monitoring`, "
            "`rollback kps 3 -n monitoring`. Always give -n <namespace>."
        ),
        # No `get`: `helm get values|manifest` prints passwords and Secret objects.
        read_only_prefixes=["list", "ls", "status", "history", "show chart", "search", "version"],
    ),
]  # fmt: skip

__all__ = ["COMMAND", "NAME", "TEMPLATES", "CustomToolDef", "build_spec"]
