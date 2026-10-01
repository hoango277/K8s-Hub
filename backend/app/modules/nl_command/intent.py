"""Is a CLI call a read or a change? — for custom tools (kubectl-ai style).

kubectl-ai guesses from a verb table and asks the human when unsure. Here the
engineer who defines a custom tool lists its read-only subcommands
(`read_only_prefixes`); a call is a READ only when its arguments start with
one of them, token by token. Everything else is a CHANGE and goes through
approval. Unknown means change: the safe side.

Because nothing runs through a shell (argv is a list), there is no `;` or
`&&` to smuggle a second command after a read-only prefix.
"""

from __future__ import annotations

import shlex
from typing import Literal

from app.modules.tools.guard import ToolInputError

MAX_ARGUMENTS_CHARS = 2000
MAX_TOKENS = 60

# Never-ending: they would hang the sandbox until the time limit.
_STREAMING = frozenset({"-w", "--watch", "--watch-only", "--follow"})
# Interactive only next to these subcommands (`helm upgrade -i` means --install).
_TTY_FLAGS = frozenset({"-it", "-ti", "-i", "-t", "--stdin", "--tty"})
_TTY_SUBCOMMANDS = frozenset({"exec", "run", "debug"})
_NEVER = frozenset({"port-forward", "proxy", "attach", "edit"})
_SECRET_WORDS = frozenset({"secret", "secrets"})

Intent = Literal["read", "write"]


def split_arguments(command: str, arguments: str) -> list[str]:
    """The model's argument string → argv tokens (program excluded).

    A leading repeat of the program ("kubectl get pods" for the kubectl tool)
    is dropped: models do that often, as kubectl-ai also observed.
    """
    if len(arguments) > MAX_ARGUMENTS_CHARS:
        raise ToolInputError(f"Arguments are limited to {MAX_ARGUMENTS_CHARS} characters.")
    try:
        tokens = shlex.split(arguments, posix=True)
    except ValueError as exc:
        raise ToolInputError(f"Could not parse the arguments: {exc}.") from exc
    if tokens and tokens[0] == command:
        tokens = tokens[1:]
    if not tokens:
        raise ToolInputError(f"Give the arguments for {command}, e.g. a subcommand.")
    if len(tokens) > MAX_TOKENS:
        raise ToolInputError(f"At most {MAX_TOKENS} arguments.")
    return tokens


def check_tokens(tokens: list[str]) -> None:
    """Refuse what no approval should cover."""
    lowered = [t.lower() for t in tokens]
    interactive_subcommand = bool(_TTY_SUBCOMMANDS & set(lowered))
    for t in lowered:
        if t in _NEVER:
            raise ToolInputError(f"'{t}' is interactive or long-running and can't be used here.")
        if (
            t in _STREAMING
            or (t == "-f" and "logs" in lowered)
            or (t in _TTY_FLAGS and interactive_subcommand)
        ):
            raise ToolInputError(
                f"'{t}' waits for input or streams forever. Use a one-shot form instead, e.g. "
                "`logs --tail=100` instead of `logs -f`."
            )
        head = t.split("/", 1)[0].split(".", 1)[0]
        if t in _SECRET_WORDS or head in _SECRET_WORDS:
            raise ToolInputError(
                "Secrets are never read or changed through K8s-Hub: their values would leak."
            )


def classify(tokens: list[str], read_only_prefixes: list[str]) -> Intent:
    for prefix in read_only_prefixes:
        words = prefix.split()
        if words and tokens[: len(words)] == words:
            return "read"
    return "write"


def namespace_of(tokens: list[str]) -> str | None:
    """-n X / --namespace X / --namespace=X, as kubectl and helm take it."""
    for i, t in enumerate(tokens):
        if t in ("-n", "--namespace") and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith("--namespace="):
            return t.split("=", 1)[1]
        if t.startswith("-n") and len(t) > 2 and not t.startswith("--"):
            return t[2:]
    return None


def spans_all_namespaces(tokens: list[str]) -> bool:
    return "-A" in tokens or "--all-namespaces" in tokens


__all__ = [
    "Intent",
    "check_tokens",
    "classify",
    "namespace_of",
    "spans_all_namespaces",
    "split_arguments",
]
