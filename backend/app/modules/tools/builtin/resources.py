"""Built-in tools: read ANY resource kind, like `kubectl get` / `kubectl describe`.

The pod/deployment tools (kubernetes.py) stay: they know pods well enough to
say what is failing NOW versus what restarted earlier. These two cover
everything else — Services, Ingresses, Nodes, PVCs, HPAs, CRDs… — without a
tool per kind. Before them, "why can't I reach my service?" had no answer.

Guard rails, same as every tool: the model passes a kind and names, never a
command; Secrets are refused (resources.py); namespaces go through the
allowed list; output is a compact table or a trimmed YAML, never a raw dump.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import yaml
from langchain_core.tools import tool

from app.integrations.k8s import client as k8s
from app.integrations.k8s import resources as res
from app.modules.tools.guard import (
    ToolInputError,
    allowed_namespaces,
    check_name,
    check_namespace,
)
from app.modules.tools.redact import redact_object
from app.modules.tools.schema import Category, Danger, ToolSpec

MAX_ROWS = 100
# Whole-output cap: a list of every pod in the cluster can exceed a small
# model's request size (Groq answered 413 for Qwen on lab1).
MAX_LIST_CHARS = 6000
MAX_DESCRIBE_CHARS = 7000
MAX_VALUE_CHARS = 400
_SELECTOR = re.compile(r"^[A-Za-z0-9._/=,!() -]{1,200}$")


def _age(ts: str | None) -> str:
    if not ts:
        return "?"
    try:
        then = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    seconds = int((datetime.now(UTC) - then).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _ready(ready: Any, total: Any) -> str:
    return f"{ready or 0}/{total or 0}"


def _images(spec: dict[str, Any]) -> str:
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or []
    return ",".join(c.get("image", "?") for c in containers)


def _summary(kind: str, obj: dict[str, Any]) -> str:
    """The few fields `kubectl get` would show for this kind."""
    spec, status = obj.get("spec") or {}, obj.get("status") or {}
    meta = obj.get("metadata") or {}
    if kind == "Pod":
        statuses = status.get("containerStatuses") or []
        restarts = sum(int(s.get("restartCount") or 0) for s in statuses)
        ready = sum(1 for s in statuses if s.get("ready"))
        return (
            f"{status.get('phase', '?')}, ready {ready}/{len(statuses)}, "
            f"restarts {restarts}, node {spec.get('nodeName', '-')}"
        )
    if kind == "Service":
        ports = ",".join(
            f"{p.get('port')}" + (f":{p['nodePort']}" if p.get("nodePort") else "")
            + f"/{p.get('protocol', 'TCP')}"
            for p in spec.get("ports") or []
        )
        selector = ",".join(f"{k}={v}" for k, v in (spec.get("selector") or {}).items())
        return (
            f"{spec.get('type', 'ClusterIP')} {spec.get('clusterIP', '-')} ports {ports or '-'}"
            f" selector {selector or '(none: endpoints managed by hand)'}"
        )
    if kind == "Ingress":
        hosts = ",".join(r.get("host", "*") for r in spec.get("rules") or [])
        return f"class {spec.get('ingressClassName', '-')}, hosts {hosts or '*'}"
    if kind == "Node":
        conditions = {c.get("type"): c.get("status") for c in status.get("conditions") or []}
        roles = [
            k.split("/", 1)[1]
            for k in (meta.get("labels") or {})
            if k.startswith("node-role.kubernetes.io/")
        ]
        alloc = status.get("allocatable") or {}
        taints = len(spec.get("taints") or [])
        return (
            f"Ready={conditions.get('Ready', '?')}, roles {','.join(roles) or '-'}, "
            f"kubelet {(status.get('nodeInfo') or {}).get('kubeletVersion', '?')}, "
            f"allocatable cpu {alloc.get('cpu', '?')} mem {alloc.get('memory', '?')}, "
            f"{taints} taint(s)" + (", UNSCHEDULABLE" if spec.get("unschedulable") else "")
        )
    if kind in ("PersistentVolumeClaim", "PersistentVolume"):
        capacity = (status.get("capacity") or spec.get("capacity") or {}).get("storage", "?")
        other = spec.get("volumeName") or (spec.get("claimRef") or {}).get("name") or "-"
        return (
            f"{status.get('phase', '?')}, {capacity}, class {spec.get('storageClassName', '-')}, "
            f"bound to {other}"
        )
    if kind in ("Deployment", "StatefulSet"):
        return (
            f"ready {_ready(status.get('readyReplicas'), spec.get('replicas'))}, "
            f"updated {status.get('updatedReplicas', 0)}, images {_images(spec)}"
        )
    if kind == "DaemonSet":
        return (
            f"ready {_ready(status.get('numberReady'), status.get('desiredNumberScheduled'))}, "
            f"images {_images(spec)}"
        )
    if kind == "ReplicaSet":
        return f"ready {_ready(status.get('readyReplicas'), spec.get('replicas'))}"
    if kind == "Job":
        return (
            f"succeeded {status.get('succeeded', 0)}/{spec.get('completions', 1)}, "
            f"active {status.get('active', 0)}, failed {status.get('failed', 0)}"
        )
    if kind == "CronJob":
        return (
            f"schedule '{spec.get('schedule')}', suspended {bool(spec.get('suspend'))}, "
            f"last run {_age(status.get('lastScheduleTime'))} ago"
        )
    if kind == "HorizontalPodAutoscaler":
        return (
            f"{spec.get('minReplicas', 1)}–{spec.get('maxReplicas')} replicas, "
            f"current {status.get('currentReplicas', '?')}, "
            f"desired {status.get('desiredReplicas', '?')}"
        )
    if kind == "ConfigMap":
        keys = sorted([*(obj.get("data") or {}), *(obj.get("binaryData") or {})])
        return f"keys {', '.join(keys) or '(none)'}"
    if kind == "Namespace":
        return str(status.get("phase", "?"))
    if kind == "Event":
        involved = obj.get("involvedObject") or {}
        return (
            f"{obj.get('type')} {obj.get('reason')} {involved.get('kind')}/{involved.get('name')}"
            f": {(obj.get('message') or '')[:160]}"
        )
    return ""


async def _namespaces_for(kind: res.Kind, namespace: str) -> list[str | None]:
    """Which namespaces a list call covers. Empty namespace = all of them,
    unless an allowed list is set: then exactly those."""
    if not kind.namespaced:
        return [None]
    if namespace:
        return [check_namespace(namespace)]
    allowed = allowed_namespaces()
    return list(allowed) if allowed else [None]


@tool(parse_docstring=True)
async def get_resources(
    kind: str, namespace: str = "", name: str = "", label_selector: str = ""
) -> str:
    """List Kubernetes resources of ANY kind, like `kubectl get`, with the key fields.

    Use for everything the pod and deployment tools don't cover: services,
    ingresses, nodes, persistent volume claims, HPAs, statefulsets, daemonsets,
    jobs, cronjobs, configmaps (keys only), network policies, CRDs and custom
    resources. Secrets can never be read.

    Args:
        kind: kind, plural or short name as in kubectl, e.g. svc, ingress, node, pvc, hpa.
        namespace: namespace to look in; empty means all (ignored for nodes etc.).
        name: optional exact name to show just one object.
        label_selector: optional label selector, e.g. "app=api".
    """
    try:
        rkind = await res.resolve_kind(kind)
        if name:
            check_name(rkind.kind, name)
        if label_selector and not _SELECTOR.match(label_selector):
            raise ToolInputError(f"Invalid label selector: {label_selector!r}.")
        objects: list[dict[str, Any]] = []
        for ns in await _namespaces_for(rkind, namespace):
            if name:
                obj = await res.get_object(rkind, ns, name) if ns or not rkind.namespaced else None
                if obj is None and rkind.namespaced and not ns:
                    found = await res.list_objects(
                        rkind, None, field_selector=f"metadata.name={name}"
                    )
                    objects.extend(found)
                elif obj is not None:
                    objects.append(obj)
            else:
                objects.extend(
                    await res.list_objects(rkind, ns, label_selector=label_selector or None)
                )
    except (ToolInputError, k8s.K8sError) as exc:
        return str(exc)

    where = (
        f" in namespace {namespace}" if rkind.namespaced and namespace
        else " in all namespaces" if rkind.namespaced else ""
    )
    if not objects:
        target = f" named {name}" if name else ""
        sel = f" matching {label_selector}" if label_selector else ""
        return f"No {rkind.plural}{target}{sel}{where}."

    lines = [f"{len(objects)} {rkind.kind}(s){where}:"]
    for obj in objects[:MAX_ROWS]:
        meta = obj.get("metadata") or {}
        who = (
            f"{meta.get('namespace')}/{meta.get('name')}"
            if rkind.namespaced and not namespace
            else str(meta.get("name"))
        )
        summary = _summary(rkind.kind, obj)
        lines.append(
            f"- {who} (age {_age(meta.get('creationTimestamp'))})"
            + (f": {summary}" if summary else "")
        )
    text = "\n".join(lines)
    if len(text) > MAX_LIST_CHARS:
        cut = text[:MAX_LIST_CHARS].rsplit("\n", 1)[0]
        shown = cut.count("\n")
        return (
            f"{cut}\n… output cut after {shown} of {len(objects)} objects; narrow it with a "
            "namespace, a name or a label selector."
        )
    if len(objects) > MAX_ROWS:
        lines.append(
            f"… {len(objects) - MAX_ROWS} more not shown; narrow with a namespace or label."
        )
    return "\n".join(lines)


def _trim_values(obj: dict[str, Any]) -> dict[str, Any]:
    """ConfigMap values can be whole config files: keep the start of each."""
    for field in ("data", "binaryData"):
        data = obj.get(field)
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
                    data[key] = value[:MAX_VALUE_CHARS] + f"… ({len(value)} characters)"
    return obj


@tool(parse_docstring=True)
async def describe_resource(kind: str, name: str, namespace: str = "") -> str:
    """Show one object in full (trimmed YAML) and its recent events, like `kubectl describe`.

    Use after get_resources, to see a service's selector and ports, an
    ingress's rules and backends, a node's conditions and taints, a PVC's
    status, a custom resource's spec… Not for pods: use describe_pod.

    Args:
        kind: resource kind, plural or short name, e.g. service, ingress, node, pvc.
        name: exact object name.
        namespace: the object's namespace (leave empty for cluster-wide kinds such as node).
    """
    try:
        rkind = await res.resolve_kind(kind)
        check_name(rkind.kind, name)
        ns = check_namespace(namespace) if rkind.namespaced else None
        if rkind.namespaced and not ns:
            raise ToolInputError(f"{rkind.kind} is namespaced: give its namespace.")
        obj = await res.get_object(rkind, ns, name)
        if obj is None:
            where = f" in namespace {ns}" if ns else ""
            return f"{rkind.kind} {name!r} not found{where}."
        events: list[dict[str, Any]] = []
        if rkind.kind != "Event":
            ev_kind = await res.resolve_kind("events")
            events = await res.list_objects(
                ev_kind,
                ns if ns else "default",
                field_selector=f"involvedObject.name={name},involvedObject.kind={rkind.kind}",
                limit=50,
            )
    except (ToolInputError, k8s.K8sError) as exc:
        return str(exc)

    # Redacted by structure before it becomes YAML: in YAML an env var's name and
    # value sit on different lines, and no text pattern could pair them again.
    body = yaml.safe_dump(
        _trim_values(redact_object(res.clean(obj))), sort_keys=False, allow_unicode=True
    )
    if len(body) > MAX_DESCRIBE_CHARS:
        body = body[:MAX_DESCRIBE_CHARS] + "\n… (cut; ask for a specific field if needed)"
    lines = [f"{rkind.kind} {ns + '/' if ns else ''}{name}:", body.rstrip()]
    events.sort(key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "", reverse=True)
    if events:
        lines.append("Recent events:")
        for e in events[:15]:
            when = _age(e.get("lastTimestamp") or e.get("eventTime"))
            lines.append(
                f"- {when} ago {e.get('type')} {e.get('reason')} (x{e.get('count') or 1}): "
                f"{(e.get('message') or '')[:200]}"
            )
    else:
        lines.append("Recent events: none.")
    return "\n".join(lines)


def _unavailable() -> str | None:
    return k8s.config_problem()


TOOLS = [
    ToolSpec(
        get_resources, "Get resources", Category.KUBERNETES, Danger.READ, unavailable=_unavailable
    ),
    ToolSpec(
        describe_resource,
        "Describe resource",
        Category.KUBERNETES,
        Danger.READ,
        unavailable=_unavailable,
    ),
]

__all__ = ["TOOLS", "describe_resource", "get_resources"]
