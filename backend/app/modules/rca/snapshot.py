"""One read of everything an RCA run needs from the Kubernetes API — for the whole cluster.

One `list` per kind ACROSS namespaces (plus nodes): ~14 requests per run,
whatever the number of namespaces or detectors, and every detector sees the
same moment of the cluster. Reading the whole cluster is what lets a
diagnosis follow a dependency into another namespace (langfuse → database);
which namespaces are actually ANALYSED is decided later (pipeline scope).

K8S_ALLOWED_NAMESPACES still applies: only those namespaces are listed, so
nothing downstream can see the others.

A kind that can't be listed (RBAC, CRD absent) is recorded in `warnings` and
left empty. Secrets are never listed (resources.py refuses them): pods only
reveal which Secret NAMES they reference.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.integrations.k8s import resources as res
from app.integrations.k8s.client import K8sError
from app.modules.tools.guard import allowed_namespaces

# kind name as resources.resolve_kind accepts it -> attribute on Snapshot
_NAMESPACED = {
    "pod": "pods",
    "replicaset": "replicasets",
    "deployment": "deployments",
    "statefulset": "statefulsets",
    "daemonset": "daemonsets",
    "controllerrevision": "controllerrevisions",
    "service": "services",
    "endpoints": "endpoints",
    "ingress": "ingresses",
    "persistentvolumeclaim": "pvcs",
    "configmap": "configmaps",
    "horizontalpodautoscaler": "hpas",
    "event": "events",
}
# The API returns the first page only; events and ReplicaSets add up fast.
_LIMITS = {"event": 3000, "pod": 2000, "replicaset": 3000, "configmap": 2000}


@dataclass
class Snapshot:
    taken_at: datetime
    pods: list[dict[str, Any]] = field(default_factory=list)
    replicasets: list[dict[str, Any]] = field(default_factory=list)
    deployments: list[dict[str, Any]] = field(default_factory=list)
    statefulsets: list[dict[str, Any]] = field(default_factory=list)
    daemonsets: list[dict[str, Any]] = field(default_factory=list)
    controllerrevisions: list[dict[str, Any]] = field(default_factory=list)
    services: list[dict[str, Any]] = field(default_factory=list)
    endpoints: list[dict[str, Any]] = field(default_factory=list)
    ingresses: list[dict[str, Any]] = field(default_factory=list)
    pvcs: list[dict[str, Any]] = field(default_factory=list)
    configmaps: list[dict[str, Any]] = field(default_factory=list)
    hpas: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    # Secrets: metadata ONLY (resources.list_secret_metadata) — change times for
    # SecretChange, and Helm's release records. Never values.
    secret_metadata: list[dict[str, Any]] = field(default_factory=list)
    # Argo CD Applications (empty when Argo CD isn't installed).
    argocd_apps: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def namespaces(self) -> list[str]:
        """Namespaces that have workloads, pods or services in the snapshot."""
        seen = {
            namespace_of(o)
            for attr in ("pods", "deployments", "statefulsets", "daemonsets", "services")
            for o in getattr(self, attr)
        }
        return sorted(n for n in seen if n)


def namespace_of(obj: dict[str, Any]) -> str | None:
    return (obj.get("metadata") or {}).get("namespace")


def in_scope(obj: dict[str, Any], namespaces: set[str] | None) -> bool:
    """`namespaces` None = every namespace (a cluster-wide diagnosis)."""
    return namespaces is None or namespace_of(obj) in namespaces


async def _list(kind_name: str, allowed: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    limit = _LIMITS.get(kind_name, 1000)
    try:
        kind = await res.resolve_kind(kind_name)
        if not allowed:
            return await res.list_objects(kind, None, limit=limit), None
        # A restricted deployment never asks for more than it may see.
        lists = await asyncio.gather(*(res.list_objects(kind, ns, limit=limit) for ns in allowed))
        return [o for items in lists for o in items], None
    except K8sError as exc:
        return [], str(exc)


async def _nodes() -> tuple[list[dict[str, Any]], str | None]:
    try:
        return await res.list_objects(await res.resolve_kind("node"), None, limit=500), None
    except K8sError as exc:
        return [], str(exc)


async def _secret_metadata(allowed: list[str]) -> tuple[list[dict[str, Any]], str | None]:
    try:
        if not allowed:
            return await res.list_secret_metadata(), None
        lists = await asyncio.gather(*(res.list_secret_metadata(ns) for ns in allowed))
        return [s for items in lists for s in items], None
    except K8sError as exc:
        return [], str(exc)


async def _argocd_apps(allowed: list[str]) -> list[dict[str, Any]]:
    try:
        kind = await res.resolve_kind("applications.argoproj.io")
        return await res.list_objects(kind, None, limit=500)
    except K8sError:
        return []  # no Argo CD on this cluster, or not visible: nothing to report


async def take() -> Snapshot:
    snap = Snapshot(taken_at=datetime.now(UTC))
    allowed = allowed_namespaces()
    names = list(_NAMESPACED)
    (secrets, secret_error), apps = await asyncio.gather(
        _secret_metadata(allowed), _argocd_apps(allowed)
    )
    snap.secret_metadata, snap.argocd_apps = secrets, apps
    if secret_error:
        snap.warnings.append(f"Secret and Helm change history unknown: {secret_error}")
    results = await asyncio.gather(*(_list(n, allowed) for n in names), _nodes())
    failed: dict[str, list[str]] = {}
    for name, (items, warning) in zip([*names, "node"], results, strict=True):
        setattr(snap, _NAMESPACED.get(name, "nodes"), items)
        if warning:
            failed.setdefault(warning, []).append(name)
    # One line per distinct error: a missing kubeconfig fails every kind alike.
    for error, kinds in failed.items():
        snap.warnings.append(f"Could not list {', '.join(kinds)}: {error}")
    return snap


__all__ = ["Snapshot", "in_scope", "namespace_of", "take"]
