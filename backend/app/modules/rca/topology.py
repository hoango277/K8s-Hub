"""The dependency graph between cluster objects — Groot's "service dependency graph".

Built for the WHOLE cluster: a diagnosis of `langfuse` must be able to follow
its database into `database`. Structure comes from Kubernetes itself, which is
exact and always there:

  Workload ─owns→ Pod ─runs_on→ Node
  Service ─selects→ Pod            Service ─backs→ Workload (selector vs template labels)
  Ingress ─routes→ Service         Pod ─refers→ ConfigMap/Secret ─mounts→ PVC
  HPA ─scales→ Workload

"Calls" (workload A sends requests to service/workload B) come from every
source available, and each edge remembers which ones saw it (`dependencies`):

  config      host names in env values and referenced ConfigMaps
              (`pg-rw.database.svc.cluster.local`, `redis://langfuse-redis:6379`)
  annotation  `k8s-hub.io/depends-on: "api, database/pg-rw"`
  metric      Beyla client metrics (detectors/dependencies.py)
  trace       span parent/child across services (detectors/traces.py)
  log         host names in error lines ("connection refused to pg-rw.database…")

Rules (rules.py) never walk this graph freely: each names one relation — or a
chain like `owner+callee+pods` — to follow from the effect's entity to where
its cause may be (`related()`).
"""

from __future__ import annotations

import re
from collections import defaultdict, deque
from typing import Any

from app.modules.rca.model import Entity
from app.modules.rca.snapshot import Snapshot

DEPENDS_ON_ANNOTATION = "k8s-hub.io/depends-on"
_WORKLOAD_KINDS = ("Deployment", "StatefulSet", "DaemonSet")

# Host names inside configuration values.
_URL_HOST = re.compile(r"[a-z][a-z0-9+.-]*://(?:[^@/\s]*@)?([a-z0-9][a-z0-9.-]*)", re.I)
_HOST_PORT = re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9.-]*[a-z0-9]):\d{2,5}\b", re.I)
_DOTTED = re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+)(?![\w-])", re.I)
_BARE = re.compile(r"[a-z0-9][a-z0-9.-]*[a-z0-9]", re.I)
# A bare value like `langfuse-redis` only counts as a host when the variable
# says so — otherwise DATABASE_NAME=langfuse would "call" a Service named langfuse.
_HOSTISH_VAR = re.compile(
    r"HOST|URL|URI|ADDR|ENDPOINT|SERVER|DSN|CONN|BROKER|UPSTREAM|BACKEND", re.I
)


def workload(ns: str, name: str, sub: str = "") -> Entity:
    return Entity("Workload", ns, name, sub)


def _meta(obj: dict[str, Any]) -> dict[str, Any]:
    return obj.get("metadata") or {}


def _matches(selector: dict[str, str], labels: dict[str, str]) -> bool:
    return bool(selector) and all(labels.get(k) == v for k, v in selector.items())


def candidate_hosts(value: str, var_name: str | None = None) -> set[str]:
    """Strings in `value` that may name a host. resolve_host() decides which are real."""
    found = set(_URL_HOST.findall(value)) | set(_HOST_PORT.findall(value))
    found |= set(_DOTTED.findall(value))
    bare = value.strip()
    if var_name and _HOSTISH_VAR.search(var_name) and _BARE.fullmatch(bare):
        found.add(bare)
    return {h.lower().rstrip(".") for h in found}


class Topology:
    """Directed relations, stored both ways so any rule can look either direction."""

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], set[Entity]] = defaultdict(set)
        self.entities: dict[str, Entity] = {}
        # Workload key -> its pod-template labels.
        self.template_labels: dict[str, dict[str, str]] = {}
        # (namespace, ReplicaSet name) -> (workload kind, name); owners of deleted pods.
        self.rs_owner: dict[tuple[str, str], tuple[str, str]] = {}
        # (caller key, callee key) -> sources that saw the call (config, metric, trace…)
        self.dependencies: dict[tuple[str, str], set[str]] = defaultdict(set)

    # --- building -----------------------------------------------------------

    def add(self, entity: Entity) -> Entity:
        # Keep the first one registered (it carries the real workload kind in `sub`).
        return self.entities.setdefault(entity.key, entity)

    def link(self, src: Entity, relation: str, dst: Entity, inverse: str) -> None:
        src, dst = self.add(src), self.add(dst)
        self._edges[(src.key, relation)].add(dst)
        self._edges[(dst.key, inverse)].add(src)

    def resolve_host(
        self, host: str, from_ns: str | None, *, by_prefix: bool = False
    ) -> Entity | None:
        """The Service a host name points to, or None (external, unknown, a typo).

        `svc` (same namespace), `svc.ns`, `svc.ns.svc[.cluster.local]`, and a
        headless pod address `pod-0.svc.ns.svc…`.

        `by_prefix`: also accept the ONE Service of that namespace whose name
        starts with `<name>-` — Beyla reports `langfuse-clickhouse` for calls
        that go to Service `langfuse-clickhouse-headless`. Two candidates =
        ambiguous = no answer, rather than a wrong edge.
        """
        labels = host.lower().rstrip(".").split(".")
        if "svc" in labels:
            i = labels.index("svc")
            if i < 2:
                return None
            name, ns = labels[i - 2], labels[i - 1]
        elif len(labels) == 1 and from_ns:
            name, ns = labels[0], from_ns
        elif len(labels) == 2:
            name, ns = labels
        else:
            return None
        exact = self.entities.get(Entity("Service", ns, name).key)
        if exact is not None or not by_prefix:
            return exact
        prefix = f"Service/{ns}/{name}-"
        matches = [e for k, e in self.entities.items() if k.startswith(prefix)]
        return matches[0] if len(matches) == 1 else None

    def add_dependency(self, caller: Entity, target: Entity, source: str) -> bool:
        """`caller` (a workload) sends requests to `target` (a Service or workload)."""
        caller = self.entities.get(caller.key) or self.add(caller)
        target = self.entities.get(target.key) or self.add(target)
        if caller.key == target.key:
            return False
        self.dependencies[(caller.key, target.key)].add(source)
        if target.kind == "Service":
            self.link(caller, "calls_service", target, "service_callers")
            for backend in self._edges.get((target.key, "backend_workloads"), set()):
                if backend.key != caller.key:
                    self.link(caller, "callee", backend, "caller")
        else:
            self.link(caller, "callee", target, "caller")
        return True

    # --- reading ------------------------------------------------------------

    def related(self, entity: Entity, relation: str) -> set[Entity]:
        """Entities reachable from `entity` over one relation or a chain (`owner+callee`)."""
        current = {self.entities.get(entity.key, entity)}
        for step in relation.split("+"):
            current = {e for c in current for e in self._step(c, step)}
        return current

    def _step(self, entity: Entity, relation: str) -> set[Entity]:
        if relation == "same":
            return {entity}
        if relation == "any_node":
            return {e for e in self.entities.values() if e.kind == "Node"}
        if relation == "callee_services":
            # Services it calls directly, and those in front of the workloads it calls.
            direct = self._edges.get((entity.key, "calls_service"), set())
            fronts = {
                svc
                for callee in self._edges.get((entity.key, "callee"), set())
                for svc in self._edges.get((callee.key, "backed_by"), set())
            }
            return set(direct) | fronts
        return set(self._edges.get((entity.key, relation), set()))

    def pod_owner(self, pod: Entity) -> Entity | None:
        owners = self._edges.get((pod.key, "owner"), set())
        return next(iter(owners), None)

    def workloads_in(self, namespaces: set[str]) -> list[Entity]:
        return [
            self.entities[k]
            for k in self.template_labels
            if self.entities[k].namespace in namespaces
        ]

    def dependency_namespaces(self, namespaces: set[str], depth: int = 2) -> set[str]:
        """Namespaces reachable from workloads in `namespaces` over "calls" edges.

        Groot builds its dependency graph around the alerted service instead of
        for everything; this is that expansion, `depth` hops out.
        """
        seen = set(namespaces)
        frontier = deque((w, 0) for w in self.workloads_in(namespaces))
        visited = {w.key for w, _ in frontier}
        while frontier:
            w, d = frontier.popleft()
            if d >= depth:
                continue
            for nxt in self._step(w, "callee") | self._step(w, "calls_service"):
                if nxt.namespace:
                    seen.add(nxt.namespace)
                if nxt.kind == "Workload" and nxt.key not in visited:
                    visited.add(nxt.key)
                    frontier.append((nxt, d + 1))
        return seen

    def dependencies_json(self) -> list[dict[str, Any]]:
        return [
            {"caller": caller, "callee": callee, "sources": sorted(sources)}
            for (caller, callee), sources in sorted(self.dependencies.items())
        ]

    def ensure_pod(self, namespace: str, name: str) -> Entity:
        """The pod, linked to its owner even when it no longer exists.

        Event history (Loki) mentions pods that were replaced since — exactly
        the crashed ones. Their names still tell the owner: `<replicaset>-<5>`
        for Deployments, `<statefulset>-<ordinal>` for StatefulSets.
        """
        pod = Entity("Pod", namespace, name)
        if pod.key in self.entities:
            return self.entities[pod.key]
        pod = self.add(pod)
        base = name.rsplit("-", 1)[0]
        owner = self.rs_owner.get((namespace, base))
        if owner is None:
            for key in self.template_labels:
                w = self.entities[key]
                if w.namespace == namespace and w.sub in ("StatefulSet", "DaemonSet"):
                    if base == w.name:
                        owner = (w.sub, w.name)
                        break
        if owner and owner[0] in _WORKLOAD_KINDS:
            self.link(pod, "owner", workload(namespace, owner[1], owner[0]), "pods")
        return pod


# Relations a rule may follow, from the EFFECT's entity to where a CAUSE may sit.
# Chains join them with "+": "owner+callee+pods" = pod → its workload → the
# workloads it calls → their pods.
RELATIONS = {
    "same": "the same object",
    "owner": "pod → the workload that owns it",
    "pods": "workload or service → its pods",
    "node": "pod → the node it runs on",
    "any_node": "pod → any node (scheduling looks at all of them)",
    "config": "pod → ConfigMaps/Secrets it references",
    "volume": "pod → PVCs it mounts",
    "backends": "service → pods it selects",
    "backend_workloads": "service → workloads whose pods it selects",
    "services": "pod → services selecting it",
    "callee": "workload → workloads it calls",
    "caller": "workload → workloads that call it",
    "calls_service": "workload → services it calls directly",
    "service_callers": "service → workloads that call it",
    "node_pods": "node → pods running on it",
    "used_by": "ConfigMap/Secret → pods referencing it",
    "mounted_by": "PVC → pods mounting it",
    "backed_by": "workload → services in front of it",
    "scales": "autoscaler → the workload it scales",
    "callee_services": "workload → services it calls, directly or in front of called workloads",
    "hpa": "workload → its autoscaler",
}


def relation_known(relation: str) -> bool:
    return all(step in RELATIONS for step in relation.split("+"))


def _owner_of(
    obj: dict[str, Any], rs_owner: dict[tuple[str, str], tuple[str, str]]
) -> tuple[str, str] | None:
    ns = _meta(obj).get("namespace") or ""
    for ref in _meta(obj).get("ownerReferences") or []:
        kind, name = ref.get("kind"), ref.get("name")
        if kind == "ReplicaSet":
            return rs_owner.get((ns, name), ("ReplicaSet", name))
        if kind in _WORKLOAD_KINDS:
            return kind, name
    return None


def _template_spec(obj: dict[str, Any]) -> dict[str, Any]:
    return ((obj.get("spec") or {}).get("template") or {}).get("spec") or {}


def _config_dependencies(
    topo: Topology,
    w: Entity,
    spec: dict[str, Any],
    configmaps: dict[tuple[str, str], dict[str, str]],
) -> None:
    """Hosts named in the workload's env and in the ConfigMaps it reads."""
    ns = w.namespace or ""
    pairs: list[tuple[str | None, str]] = []
    for c in [*(spec.get("containers") or []), *(spec.get("initContainers") or [])]:
        for env in c.get("env") or []:
            if isinstance(env.get("value"), str):
                pairs.append((env.get("name"), env["value"]))
            ref = (env.get("valueFrom") or {}).get("configMapKeyRef") or {}
            if ref.get("name"):
                value = configmaps.get((ns, ref["name"]), {}).get(ref.get("key", ""))
                if value:
                    pairs.append((env.get("name"), value))
            # secretKeyRef: never read — Secret values don't leave the cluster.
        for src in c.get("envFrom") or []:
            name = (src.get("configMapRef") or {}).get("name")
            pairs += list(configmaps.get((ns, name or ""), {}).items())
    for vol in spec.get("volumes") or []:
        name = (vol.get("configMap") or {}).get("name")
        # Mounted config files: only dotted/URL/host:port forms, no variable names.
        pairs += [(None, v) for v in configmaps.get((ns, name or ""), {}).values()]
    for var, value in pairs:
        for host in candidate_hosts(value[:4000], var):
            svc = topo.resolve_host(host, ns)
            if svc is not None:
                topo.add_dependency(w, svc, "config")


def build(snap: Snapshot) -> Topology:
    topo = Topology()
    workload_objs: list[tuple[Entity, dict[str, Any]]] = []

    for kind, items in (
        ("Deployment", snap.deployments),
        ("StatefulSet", snap.statefulsets),
        ("DaemonSet", snap.daemonsets),
    ):
        for obj in items:
            m = _meta(obj)
            w = topo.add(workload(m.get("namespace") or "", m["name"], kind))
            tmpl = ((obj.get("spec") or {}).get("template") or {}).get("metadata") or {}
            topo.template_labels[w.key] = dict(tmpl.get("labels") or {})
            workload_objs.append((w, obj))

    for rs in snap.replicasets:
        owner = _owner_of(rs, {})
        if owner:
            topo.rs_owner[(_meta(rs).get("namespace") or "", _meta(rs)["name"])] = owner

    for node in snap.nodes:
        topo.add(Entity("Node", None, _meta(node)["name"]))

    pods_by_ns: dict[str, list[tuple[Entity, dict[str, str]]]] = defaultdict(list)
    for pod in snap.pods:
        meta, spec = _meta(pod), pod.get("spec") or {}
        ns = meta.get("namespace") or ""
        p = topo.add(Entity("Pod", ns, meta["name"]))
        pods_by_ns[ns].append((p, meta.get("labels") or {}))
        owner = _owner_of(pod, topo.rs_owner)
        if owner and owner[0] in _WORKLOAD_KINDS:
            topo.link(p, "owner", workload(ns, owner[1], owner[0]), "pods")
        if spec.get("nodeName"):
            topo.link(p, "node", Entity("Node", None, spec["nodeName"]), "node_pods")
        for vol in spec.get("volumes") or []:
            if vol.get("persistentVolumeClaim"):
                claim = vol["persistentVolumeClaim"].get("claimName")
                topo.link(p, "volume", Entity("PVC", ns, claim), "mounted_by")
            if vol.get("configMap"):
                cm = Entity("ConfigMap", ns, vol["configMap"].get("name"))
                topo.link(p, "config", cm, "used_by")
            if vol.get("secret"):
                secret = Entity("Secret", ns, vol["secret"].get("secretName"))
                topo.link(p, "config", secret, "used_by")
        for c in [*(spec.get("containers") or []), *(spec.get("initContainers") or [])]:
            for src in c.get("envFrom") or []:
                for key, kind in (("configMapRef", "ConfigMap"), ("secretRef", "Secret")):
                    if src.get(key, {}).get("name"):
                        topo.link(p, "config", Entity(kind, ns, src[key]["name"]), "used_by")
            for env in c.get("env") or []:
                ref = env.get("valueFrom") or {}
                for key, kind in (("configMapKeyRef", "ConfigMap"), ("secretKeyRef", "Secret")):
                    if ref.get(key, {}).get("name"):
                        topo.link(p, "config", Entity(kind, ns, ref[key]["name"]), "used_by")

    for svc in snap.services:
        ns = _meta(svc).get("namespace") or ""
        s = topo.add(Entity("Service", ns, _meta(svc)["name"]))
        selector = (svc.get("spec") or {}).get("selector") or {}
        for pod, labels in pods_by_ns.get(ns, []):
            if _matches(selector, labels):
                topo.link(s, "backends", pod, "services")
        for wkey, labels in topo.template_labels.items():
            if topo.entities[wkey].namespace == ns and _matches(selector, labels):
                topo.link(s, "backend_workloads", topo.entities[wkey], "backed_by")

    for ing in snap.ingresses:
        ns = _meta(ing).get("namespace") or ""
        i = Entity("Ingress", ns, _meta(ing)["name"])
        for rule in (ing.get("spec") or {}).get("rules") or []:
            for path in ((rule.get("http") or {}).get("paths")) or []:
                svc = ((path.get("backend") or {}).get("service") or {}).get("name")
                if svc:
                    topo.link(i, "routes", Entity("Service", ns, svc), "routed_by")

    for hpa in snap.hpas:
        ns = _meta(hpa).get("namespace") or ""
        ref = (hpa.get("spec") or {}).get("scaleTargetRef") or {}
        if ref.get("kind") in _WORKLOAD_KINDS:
            w = workload(ns, ref["name"], ref["kind"])
            topo.link(w, "hpa", Entity("HPA", ns, _meta(hpa)["name"]), "scales")

    # Dependencies last: they need Services and their backends to resolve.
    configmaps = {
        (_meta(cm).get("namespace") or "", _meta(cm)["name"]): {
            k: v for k, v in (cm.get("data") or {}).items() if isinstance(v, str)
        }
        for cm in snap.configmaps
    }
    for w, obj in workload_objs:
        ns = w.namespace or ""
        annotation = str((_meta(obj).get("annotations") or {}).get(DEPENDS_ON_ANNOTATION, ""))
        for target in filter(None, (t.strip() for t in annotation.split(","))):
            t_ns, _, t_name = target.rpartition("/")
            t_ns = t_ns or ns
            svc = topo.entities.get(Entity("Service", t_ns, t_name).key)
            topo.add_dependency(w, svc or workload(t_ns, t_name), "annotation")
        _config_dependencies(topo, w, _template_spec(obj), configmaps)
    return topo


__all__ = [
    "DEPENDS_ON_ANNOTATION",
    "RELATIONS",
    "Topology",
    "build",
    "candidate_hosts",
    "relation_known",
    "workload",
]
