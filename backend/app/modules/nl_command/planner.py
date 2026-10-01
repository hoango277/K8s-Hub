"""Turn a structured request into an exact, storable plan.

A plan is DATA: the REST calls to make (or the argv to run), plus how to
verify the outcome. It is built once, dry-run, shown to the approver, stored
in `approvals.plan`, and executed as stored. The model never gets a second
chance to change what runs after a human said yes.

Every builder validates its input (names, namespaces, protected namespaces,
the target exists) so a bad request is refused before anyone sees a card.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import yaml

from app.integrations.k8s import resources as res
from app.modules.nl_command.guardrails import check_write_namespace, danger_of_kind
from app.modules.tools.guard import ToolInputError, check_name

FIELD_MANAGER = "k8s-hub"
MAX_MANIFEST_CHARS = 30_000
MAX_DOCUMENTS = 10
MAX_REPLICAS = 50
# registry/path:tag or @sha256:…, as the kubelet accepts.
_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._\-/:@]{0,254}$", re.IGNORECASE)

WorkloadKind = Literal["deployment", "statefulset", "daemonset"]
_WORKLOADS = {"deployment": "Deployment", "statefulset": "StatefulSet", "daemonset": "DaemonSet"}

Danger = Literal["caution", "dangerous"]


@dataclass
class K8sOp:
    """One REST call. `query` gets dryRun=All added for the dry-run."""

    method: str
    path: str
    kind: str
    name: str
    namespace: str | None
    body: Any = None
    content_type: str = "application/json"
    query: list[list[Any]] = field(default_factory=list)
    # Where to GET the object before/after, for the diff. None = same as path.
    read_path: str | None = None


@dataclass
class ActionPlan:
    kind: str  # scale | restart | set_image | delete_pod | apply | command
    title: str
    danger: Danger
    namespace: str | None = None
    target: str | None = None
    ops: list[K8sOp] = field(default_factory=list)
    # kind == "mcp": {server_id, server, url, tool, args} — a call to an external tool.
    mcp: dict[str, Any] | None = None
    # kind == "command": the program and its arguments, run in the sandbox.
    argv: list[str] | None = None
    time_limit: int = 60
    # {"type": "rollout"|"deleted"|"exists"|"exit_code", …}
    verify: dict[str, Any] | None = None
    # Shown on the card: what the approver should know that the diff doesn't say.
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ActionPlan:
        data = dict(data)
        data["ops"] = [K8sOp(**op) for op in data.get("ops") or []]
        return cls(**data)


async def _workload(kind: WorkloadKind, namespace: str, name: str) -> tuple[res.Kind, dict]:
    if kind not in _WORKLOADS:
        raise ToolInputError("kind must be deployment, statefulset or daemonset.")
    check_write_namespace(namespace)
    check_name(kind, name)
    rkind = await res.resolve_kind(_WORKLOADS[kind])
    obj = await res.get_object(rkind, namespace, name)
    if obj is None:
        raise ToolInputError(f"{rkind.kind} {namespace}/{name} does not exist.")
    return rkind, obj


def _rollout(rkind: res.Kind, namespace: str, name: str) -> dict[str, Any]:
    return {"type": "rollout", "kind": rkind.kind, "namespace": namespace, "name": name}


async def plan_scale(kind: WorkloadKind, namespace: str, name: str, replicas: int) -> ActionPlan:
    if kind == "daemonset":
        raise ToolInputError("A DaemonSet runs one pod per node; it can't be scaled.")
    if not 0 <= replicas <= MAX_REPLICAS:
        raise ToolInputError(f"replicas must be between 0 and {MAX_REPLICAS}.")
    rkind, obj = await _workload(kind, namespace, name)
    current = (obj.get("spec") or {}).get("replicas", 1)
    notes = []
    if replicas == 0:
        notes.append("Scaling to 0 stops every pod: the workload serves nothing until scaled up.")
    hpas = await res.list_objects(await res.resolve_kind("hpa"), namespace)
    for hpa in hpas:
        ref = (hpa.get("spec") or {}).get("scaleTargetRef") or {}
        if ref.get("kind") == rkind.kind and ref.get("name") == name:
            notes.append(
                f"HPA {hpa['metadata']['name']} manages this workload and will override the "
                "replica count; change the HPA instead."
            )
    return ActionPlan(
        kind="scale",
        title=(
            f"Scale {rkind.kind.lower()} {namespace}/{name} from {current} to {replicas} replicas"
        ),
        danger="dangerous" if replicas == 0 else "caution",
        namespace=namespace,
        target=f"{rkind.kind}/{name}",
        ops=[
            K8sOp(
                "PATCH",
                rkind.path(namespace, name),
                rkind.kind,
                name,
                namespace,
                body={"spec": {"replicas": replicas}},
                content_type="application/merge-patch+json",
            )
        ],
        verify=_rollout(rkind, namespace, name),
        notes=notes,
    )


async def plan_restart(kind: WorkloadKind, namespace: str, name: str) -> ActionPlan:
    rkind, _ = await _workload(kind, namespace, name)
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    # Exactly what `kubectl rollout restart` does: bump a pod-template annotation.
    body = {
        "spec": {
            "template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": stamp}}}
        }
    }
    return ActionPlan(
        kind="restart",
        title=f"Restart {rkind.kind.lower()} {namespace}/{name} (rolling)",
        danger="caution",
        namespace=namespace,
        target=f"{rkind.kind}/{name}",
        ops=[
            K8sOp(
                "PATCH",
                rkind.path(namespace, name),
                rkind.kind,
                name,
                namespace,
                body=body,
                content_type="application/strategic-merge-patch+json",
            )
        ],
        verify=_rollout(rkind, namespace, name),
    )


async def plan_set_image(
    kind: WorkloadKind, namespace: str, name: str, container: str, image: str
) -> ActionPlan:
    if not _IMAGE.match(image):
        raise ToolInputError(f"Invalid image reference: {image!r}.")
    rkind, obj = await _workload(kind, namespace, name)
    containers = (((obj.get("spec") or {}).get("template") or {}).get("spec") or {}).get(
        "containers"
    ) or []
    names = [c.get("name") for c in containers]
    if container not in names:
        raise ToolInputError(
            f"{rkind.kind} {name} has no container {container!r}. Containers: {', '.join(names)}."
        )
    old = next(c.get("image") for c in containers if c.get("name") == container)
    notes = []
    if image.endswith(":latest") or (":" not in image.rsplit("/", 1)[-1] and "@" not in image):
        notes.append("The image has no fixed tag (or uses :latest): rollbacks won't be reliable.")
    body = {"spec": {"template": {"spec": {"containers": [{"name": container, "image": image}]}}}}
    return ActionPlan(
        kind="set_image",
        title=f"Change image of {namespace}/{name} container {container}: {old} → {image}",
        danger="caution",
        namespace=namespace,
        target=f"{rkind.kind}/{name}",
        ops=[
            K8sOp(
                "PATCH",
                rkind.path(namespace, name),
                rkind.kind,
                name,
                namespace,
                body=body,
                content_type="application/strategic-merge-patch+json",
            )
        ],
        verify=_rollout(rkind, namespace, name),
        notes=notes,
    )


# Cluster-wide kinds whose deletion breaks far more than one app. Deleting
# them is left to a human at a terminal.
_NEVER_DELETE = frozenset(
    {
        "Node", "PersistentVolume", "StorageClass", "CustomResourceDefinition",
        "ClusterRole", "ClusterRoleBinding", "IngressClass", "PriorityClass",
        "MutatingWebhookConfiguration", "ValidatingWebhookConfiguration",
    }
)  # fmt: skip
# Namespaces that exist on every cluster and that other things assume.
_KEEP_NAMESPACES = frozenset({"default"})


async def plan_delete(kind: str, namespace: str, name: str) -> ActionPlan:
    """Delete ONE object of any kind (pods have plan_delete_pod, with owner checks)."""
    rkind = await res.resolve_kind(kind)  # refuses Secrets
    if rkind.kind == "Pod":
        return await plan_delete_pod(namespace, name)
    if rkind.kind in _NEVER_DELETE:
        raise ToolInputError(
            f"Deleting a {rkind.kind} affects the whole cluster; K8s-Hub never proposes it."
        )
    check_name(rkind.kind, name)
    notes: list[str] = []
    if rkind.kind == "Namespace":
        check_write_namespace(name)  # protected namespaces can't be deleted either
        if name in _KEEP_NAMESPACES:
            raise ToolInputError(f"Namespace {name!r} is built in; K8s-Hub never deletes it.")
        ns = None
        pods = await res.list_objects(await res.resolve_kind("pod"), name)
        notes.append(
            f"Deletes EVERYTHING inside namespace {name} ({len(pods)} pod(s) now), including "
            "Secrets and volumes claims. This can't be undone."
        )
    elif rkind.namespaced:
        ns = check_write_namespace(namespace)
    else:
        ns = None
    if await res.get_object(rkind, ns, name) is None:
        where = f" in namespace {ns}" if ns else ""
        raise ToolInputError(f"{rkind.kind} {name!r} does not exist{where}.")
    label = f"{ns}/{name}" if ns else name
    return ActionPlan(
        kind="delete",
        title=f"Delete {rkind.kind.lower()} {label}",
        danger="dangerous",
        namespace=ns or (name if rkind.kind == "Namespace" else None),
        target=f"{rkind.kind}/{name}",
        ops=[K8sOp("DELETE", rkind.path(ns, name), rkind.kind, name, ns)],
        verify={"type": "deleted", "kind": rkind.kind, "namespace": ns, "name": name},
        notes=notes,
    )


async def plan_delete_pod(namespace: str, name: str) -> ActionPlan:
    check_write_namespace(namespace)
    check_name("pod", name)
    rkind = await res.resolve_kind("pod")
    pod = await res.get_object(rkind, namespace, name)
    if pod is None:
        raise ToolInputError(f"Pod {namespace}/{name} does not exist.")
    owners = (pod.get("metadata") or {}).get("ownerReferences") or []
    notes = []
    if owners:
        owner = owners[0]
        notes.append(
            f"Owned by {owner.get('kind')} {owner.get('name')}: a replacement pod is created "
            "automatically."
        )
        danger: Danger = "caution"
    else:
        notes.append("Not managed by a controller: the pod will NOT come back after deletion.")
        danger = "dangerous"
    return ActionPlan(
        kind="delete_pod",
        title=f"Delete pod {namespace}/{name}",
        danger=danger,
        namespace=namespace,
        target=f"Pod/{name}",
        ops=[K8sOp("DELETE", rkind.path(namespace, name), "Pod", name, namespace)],
        verify={"type": "deleted", "kind": "Pod", "namespace": namespace, "name": name},
        notes=notes,
    )


async def plan_apply(manifest: str) -> ActionPlan:
    """Server-side apply of up to MAX_DOCUMENTS objects, one op per object."""
    if len(manifest) > MAX_MANIFEST_CHARS:
        raise ToolInputError(f"The manifest is limited to {MAX_MANIFEST_CHARS} characters.")
    try:
        docs = [d for d in yaml.safe_load_all(manifest) if d]
    except yaml.YAMLError as exc:
        raise ToolInputError(f"The manifest is not valid YAML: {exc}") from exc
    if not docs:
        raise ToolInputError("The manifest is empty.")
    if len(docs) > MAX_DOCUMENTS:
        raise ToolInputError(f"At most {MAX_DOCUMENTS} objects per change.")

    ops: list[K8sOp] = []
    targets: list[str] = []
    namespaces: set[str] = set()
    danger: Danger = "caution"
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("apiVersion") or not doc.get("kind"):
            raise ToolInputError("Every object needs apiVersion and kind.")
        meta = doc.get("metadata") or {}
        name = meta.get("name")
        if not name:
            raise ToolInputError(f"A {doc['kind']} has no metadata.name.")
        if doc["kind"] == "List":
            raise ToolInputError("Send the objects as separate YAML documents, not a List.")
        found = await res.resolve_kind(doc["kind"])  # refuses Secrets
        rkind = res.Kind(found.kind, found.plural, str(doc["apiVersion"]), found.namespaced)
        check_name(rkind.kind, str(name))
        namespace = None
        if rkind.namespaced:
            namespace = check_write_namespace(str(meta.get("namespace") or "default"))
            doc.setdefault("metadata", {})["namespace"] = namespace
            namespaces.add(namespace)
        if danger_of_kind(rkind.kind) == "dangerous":
            danger = "dangerous"
        ops.append(
            K8sOp(
                "PATCH",
                rkind.path(namespace, str(name)),
                rkind.kind,
                str(name),
                namespace,
                body=doc,
                content_type="application/apply-patch+yaml",
                query=[["fieldManager", FIELD_MANAGER]],
            )
        )
        targets.append(f"{rkind.kind}/{name}")

    # Namespaces first, so objects inside a namespace this change creates can
    # be created after it (Kubernetes has no multi-object transaction).
    order = sorted(range(len(ops)), key=lambda i: ops[i].kind != "Namespace")
    ops = [ops[i] for i in order]
    targets = [targets[i] for i in order]
    notes = [
        f"{t}: image {img} has no fixed tag (or uses :latest), so what runs can change later."
        for t, img in _floating_images(docs)
    ]

    first = targets[0] + (f" and {len(targets) - 1} more" if len(targets) > 1 else "")
    return ActionPlan(
        kind="apply",
        title=f"Apply {first}" + (f" in {', '.join(sorted(namespaces))}" if namespaces else ""),
        danger=danger,
        namespace=next(iter(namespaces)) if len(namespaces) == 1 else None,
        target=", ".join(targets)[:300],
        ops=ops,
        notes=notes,
        verify={
            "type": "exists",
            "objects": [
                {"path": op.path, "kind": op.kind, "name": op.name, "namespace": op.namespace}
                for op in ops
            ],
        },
    )


def _floating_images(docs: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """(object, image) for containers whose image has no tag or uses :latest."""
    found = []
    for doc in docs:
        spec = doc.get("spec") or {}
        pod_spec = ((spec.get("template") or {}).get("spec")) or spec
        for c in [*(pod_spec.get("containers") or []), *(pod_spec.get("initContainers") or [])]:
            image = str(c.get("image") or "")
            last = image.rsplit("/", 1)[-1]
            if image and "@" not in image and (":" not in last or last.endswith(":latest")):
                name = (doc.get("metadata") or {}).get("name")
                found.append((f"{doc.get('kind')}/{name}", image))
    return found


def plan_mcp(
    *, server_id: str, server: str, url: str, tool: str, args: dict[str, Any]
) -> ActionPlan:
    """A call to an external MCP tool an engineer marked "requires approval".

    The URL is stored with the plan, so what runs is the server the approver
    saw; the token is looked up at execution time and never stored here.
    """
    return ActionPlan(
        kind="mcp",
        title=f"Call {tool} on MCP server {server}"[:300],
        danger="caution",
        target=f"mcp:{server}/{tool}",
        mcp={"server_id": server_id, "server": server, "url": url, "tool": tool, "args": args},
        verify={"type": "call_ok"},
        notes=[
            "External tool: K8s-Hub can't dry-run it or know what it changes. "
            "Check the arguments."
        ],
    )


def plan_command(
    tool: str, argv: list[str], *, namespace: str | None, time_limit: int, danger: Danger
) -> ActionPlan:
    shown = " ".join(argv)
    return ActionPlan(
        kind="command",
        title=f"Run: {shown}"[:300],
        danger=danger,
        namespace=namespace,
        target=tool,
        argv=argv,
        time_limit=time_limit,
        verify={"type": "exit_code"},
    )


__all__ = [
    "ActionPlan",
    "K8sOp",
    "plan_apply",
    "plan_command",
    "plan_mcp",
    "plan_delete",
    "plan_delete_pod",
    "plan_restart",
    "plan_scale",
    "plan_set_image",
]
