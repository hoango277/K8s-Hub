"""Rules every proposed change must pass BEFORE it is even dry-run.

The approval step is the main safety net, but some changes should never
reach a human's queue: writing to the control plane's namespaces, touching
Secrets, acting on every namespace at once. Refusing them here gives the
model a clear reason it can relay, instead of an approver rubber-stamping a
dangerous card at 3 a.m.
"""

from __future__ import annotations

from app.core.config import get_settings
from app.modules.tools.guard import ToolInputError, check_namespace

# Namespaces the assistant never changes: the control plane and the sandbox.
PROTECTED_NAMESPACES = frozenset({"kube-system", "kube-public", "kube-node-lease"})

# Kinds whose changes reach beyond one namespace or change who can do what.
CLUSTER_WIDE_OR_RBAC = frozenset(
    {
        "Namespace",
        "Node",
        "PersistentVolume",
        "StorageClass",
        "CustomResourceDefinition",
        "ClusterRole",
        "ClusterRoleBinding",
        "Role",
        "RoleBinding",
        "ServiceAccount",
        "MutatingWebhookConfiguration",
        "ValidatingWebhookConfiguration",
        "IngressClass",
        "PriorityClass",
    }
)


def protected_namespaces() -> frozenset[str]:
    return PROTECTED_NAMESPACES | {get_settings().SANDBOX_NAMESPACE}


def check_write_namespace(namespace: str) -> str:
    """Allowed list first (same rule as reads), then the protected set."""
    check_namespace(namespace)
    if namespace in protected_namespaces():
        raise ToolInputError(
            f"Namespace {namespace!r} is protected: K8s-Hub never changes it. "
            "Do it by hand if it is really needed."
        )
    return namespace


def check_execution_allowed() -> None:
    if get_settings().K8S_EXECUTION_MODE == "read_only":
        raise ToolInputError(
            "The system is in read_only mode: no change can be proposed. An admin can switch "
            "K8S_EXECUTION_MODE to require_approval in Settings."
        )


def danger_of_kind(kind: str) -> str:
    return "dangerous" if kind in CLUSTER_WIDE_OR_RBAC else "caution"


__all__ = [
    "CLUSTER_WIDE_OR_RBAC",
    "PROTECTED_NAMESPACES",
    "check_execution_allowed",
    "check_write_namespace",
    "danger_of_kind",
    "protected_namespaces",
]
