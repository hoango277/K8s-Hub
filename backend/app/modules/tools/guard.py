"""Checks every built-in tool applies before touching the cluster.

One place, so the namespace restriction can't be implemented slightly
differently (or forgotten) in each tool.
"""

from __future__ import annotations

import re

from app.core.config import get_settings

# Kubernetes object and namespace names (DNS-1123 subdomain / label).
_NAME = re.compile(r"^[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?$")
_NAMESPACE = re.compile(r"^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$")


class ToolInputError(ValueError):
    """Bad input from the model or the user. The message is shown as-is."""


def allowed_namespaces() -> list[str]:
    return list(get_settings().K8S_ALLOWED_NAMESPACES or [])


def check_namespace(namespace: str) -> str:
    if not _NAMESPACE.match(namespace or ""):
        raise ToolInputError(f"Invalid namespace: {namespace!r}.")
    allowed = allowed_namespaces()
    if allowed and namespace not in allowed:
        raise ToolInputError(
            f"Namespace {namespace!r} is not in the allowed list ({', '.join(allowed)})."
        )
    return namespace


def check_name(kind: str, name: str) -> str:
    if not _NAME.match(name or ""):
        raise ToolInputError(f"Invalid {kind} name: {name!r}.")
    return name


def clamp(value: int, low: int, high: int) -> int:
    return min(max(int(value), low), high)


__all__ = ["ToolInputError", "allowed_namespaces", "check_name", "check_namespace", "clamp"]
