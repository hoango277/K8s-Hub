"""Any Kubernetes resource by kind: resolve the kind, then plain REST calls.

Why not one typed client per kind: the generic tools (get/describe any kind)
and the approval flow (dry-run, apply, patch, delete) need the SAME calls for
Services, Ingresses, CRDs… A kind table plus raw requests covers them all
with one code path, and a CRD needs no code at all — it is found through API
discovery.

Secrets are refused here, at the lowest level, for every caller: their values
would go straight into the model's context (and Langfuse).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from app.integrations.k8s.client import K8sError, api_client


@dataclass(frozen=True)
class Kind:
    kind: str
    plural: str
    group_version: str  # "v1" for the core group, else "apps/v1", …
    namespaced: bool
    aliases: tuple[str, ...] = ()

    @property
    def base(self) -> str:
        return "/api/v1" if self.group_version == "v1" else f"/apis/{self.group_version}"

    def path(self, namespace: str | None = None, name: str | None = None, sub: str = "") -> str:
        parts = [self.base]
        if self.namespaced and namespace:
            parts.append(f"namespaces/{quote(namespace)}")
        parts.append(self.plural)
        if name:
            parts.append(quote(name))
        if sub:
            parts.append(sub)
        return "/".join(parts)


KINDS: tuple[Kind, ...] = (
    Kind("Pod", "pods", "v1", True, ("po",)),
    Kind("Service", "services", "v1", True, ("svc",)),
    Kind("Endpoints", "endpoints", "v1", True, ("ep",)),
    Kind("ConfigMap", "configmaps", "v1", True, ("cm",)),
    Kind("PersistentVolumeClaim", "persistentvolumeclaims", "v1", True, ("pvc",)),
    Kind("PersistentVolume", "persistentvolumes", "v1", False, ("pv",)),
    Kind("Node", "nodes", "v1", False, ("no",)),
    Kind("Namespace", "namespaces", "v1", False, ("ns",)),
    Kind("Event", "events", "v1", True, ("ev",)),
    Kind("ServiceAccount", "serviceaccounts", "v1", True, ("sa",)),
    Kind("ResourceQuota", "resourcequotas", "v1", True, ("quota",)),
    Kind("LimitRange", "limitranges", "v1", True, ("limits",)),
    Kind("Deployment", "deployments", "apps/v1", True, ("deploy",)),
    Kind("StatefulSet", "statefulsets", "apps/v1", True, ("sts",)),
    Kind("DaemonSet", "daemonsets", "apps/v1", True, ("ds",)),
    Kind("ReplicaSet", "replicasets", "apps/v1", True, ("rs",)),
    Kind("Job", "jobs", "batch/v1", True),
    Kind("CronJob", "cronjobs", "batch/v1", True, ("cj",)),
    Kind("Ingress", "ingresses", "networking.k8s.io/v1", True, ("ing",)),
    Kind("IngressClass", "ingressclasses", "networking.k8s.io/v1", False),
    Kind("NetworkPolicy", "networkpolicies", "networking.k8s.io/v1", True, ("netpol",)),
    Kind("HorizontalPodAutoscaler", "horizontalpodautoscalers", "autoscaling/v2", True, ("hpa",)),
    Kind("PodDisruptionBudget", "poddisruptionbudgets", "policy/v1", True, ("pdb",)),
    Kind("StorageClass", "storageclasses", "storage.k8s.io/v1", False, ("sc",)),
    Kind("Role", "roles", "rbac.authorization.k8s.io/v1", True),
    Kind("RoleBinding", "rolebindings", "rbac.authorization.k8s.io/v1", True),
    Kind("ClusterRole", "clusterroles", "rbac.authorization.k8s.io/v1", False),
    Kind("ClusterRoleBinding", "clusterrolebindings", "rbac.authorization.k8s.io/v1", False),
    Kind(
        "CustomResourceDefinition",
        "customresourcedefinitions",
        "apiextensions.k8s.io/v1",
        False,
        ("crd", "crds"),
    ),
)

BLOCKED_KINDS = frozenset({"secret", "secrets"})

_DISCOVERY_TTL = 300
_discovered: tuple[float, dict[str, Kind]] | None = None


def _keys(kind: Kind) -> set[str]:
    k = kind.kind.lower()
    return {k, kind.plural, *kind.aliases}


def _static(name: str) -> Kind | None:
    for kind in KINDS:
        if name in _keys(kind):
            return kind
    return None


def is_blocked(kind: str) -> bool:
    k = kind.strip().lower()
    return k in BLOCKED_KINDS or k.split(".")[0] in BLOCKED_KINDS


async def _discover() -> dict[str, Kind]:
    """Every resource the API server serves (preferred versions), incl. CRDs."""
    global _discovered
    if _discovered and time.monotonic() - _discovered[0] < _DISCOVERY_TTL:
        return _discovered[1]
    found: dict[str, Kind] = {}
    groups = await get_json("/apis")
    for group in groups.get("groups") or []:
        gv = (group.get("preferredVersion") or {}).get("groupVersion")
        if not gv:
            continue
        try:
            listing = await get_json(f"/apis/{gv}")
        except K8sError:
            continue  # an aggregated API that is down must not break discovery
        for res in listing.get("resources") or []:
            if "/" in res.get("name", ""):
                continue  # subresources: deployments/scale, pods/log…
            kind = Kind(
                res["kind"],
                res["name"],
                gv,
                bool(res.get("namespaced")),
                tuple(res.get("shortNames") or ()),
            )
            group_name = gv.split("/")[0]
            for key in (*_keys(kind), f"{res['name']}.{group_name}"):
                found.setdefault(key, kind)
    _discovered = (time.monotonic(), found)
    return found


async def resolve_kind(name: str) -> Kind:
    """'svc', 'Deployment', 'ingresses', 'certificates.cert-manager.io' → Kind."""
    key = name.strip().lower()
    if not key:
        raise K8sError("Give a resource kind, e.g. service, ingress, node.")
    if is_blocked(key):
        raise K8sError("Secrets are never read or changed by K8s-Hub: their values would leak.")
    kind = _static(key)
    if kind:
        return kind
    kind = (await _discover()).get(key)
    if kind is None:
        raise K8sError(
            f"Unknown resource kind {name!r}. Use a kind, plural or short name as kubectl does "
            "(e.g. svc, ingress, pvc, hpa)."
        )
    if is_blocked(kind.kind):
        raise K8sError("Secrets are never read or changed by K8s-Hub: their values would leak.")
    return kind


async def request(
    method: str,
    path: str,
    *,
    query: list[tuple[str, Any]] | None = None,
    body: Any = None,
    content_type: str = "application/json",
    accept: str = "application/json",
) -> tuple[int, dict[str, Any]]:
    """One REST call. Returns (status, JSON body) — errors are NOT raised, so
    callers can tell 404 (absent: create) from 403/422 (refused)."""
    async with api_client() as api:
        try:
            resp = await api.call_api(
                path,
                method,
                {},
                list(query or []),
                {"Accept": accept, "Content-Type": content_type},
                body=body,
                auth_settings=["BearerToken"],
                _preload_content=False,
                _return_http_data_only=True,
            )
            raw = await resp.read()
        except Exception as exc:
            raise K8sError(
                f"Could not reach the Kubernetes API: {type(exc).__name__}: {exc}"
            ) from exc
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {"message": raw.decode("utf-8", "replace")[:500]}
    return resp.status, data if isinstance(data, dict) else {"items": data}


# Ask the API server for metadata only: it strips `data`/`stringData` itself.
_METADATA_ONLY = "application/json;as=PartialObjectMetadataList;g=meta.k8s.io;v=v1"


async def list_secret_metadata(
    namespace: str | None = None, *, label_selector: str | None = None, limit: int = 2000
) -> list[dict[str, Any]]:
    """WHEN Secrets were created/changed and by whom — never what they contain.

    The one exception to "Secrets are never read", for root-cause analysis
    (a rotated password breaks the apps that use it; Helm keeps its release
    history in Secrets). Three layers keep values out:
      1. the server is asked for PartialObjectMetadataList, which has no data;
      2. whatever comes back is reduced here to name, namespace, labels,
         creation time and managedFields (manager/operation/time only);
      3. annotations are dropped entirely — `kubectl apply` stores the whole
         object, values included, in last-applied-configuration.
    """
    path = f"/api/v1/namespaces/{quote(namespace)}/secrets" if namespace else "/api/v1/secrets"
    query: list[tuple[str, Any]] = [("limit", limit)]
    if label_selector:
        query.append(("labelSelector", label_selector))
    status, data = await request("GET", path, query=query, accept=_METADATA_ONLY)
    if status >= 400:
        raise api_error(status, data, "Secret metadata")
    out = []
    for item in data.get("items") or []:
        m = item.get("metadata") or {}
        out.append(
            {
                "metadata": {
                    "name": m.get("name"),
                    "namespace": m.get("namespace"),
                    "labels": dict(m.get("labels") or {}),
                    "creationTimestamp": m.get("creationTimestamp"),
                    "managedFields": [
                        {k: f.get(k) for k in ("manager", "operation", "time")}
                        for f in m.get("managedFields") or []
                    ],
                }
            }
        )
    return out


def api_error(status: int, data: dict[str, Any], what: str) -> K8sError:
    """A user-facing error from a Kubernetes Status response."""
    message = str(data.get("message") or "").strip()
    if status == 404:
        return K8sError(f"{what} not found.")
    if status == 403:
        return K8sError(f"K8s-Hub is not allowed to access {what} (RBAC): {message}")
    return K8sError(f"Kubernetes refused ({status}) for {what}: {message or 'no details'}")


async def get_json(path: str, query: list[tuple[str, Any]] | None = None) -> dict[str, Any]:
    status, data = await request("GET", path, query=query)
    if status >= 400:
        raise api_error(status, data, path)
    return data


async def list_objects(
    kind: Kind,
    namespace: str | None,
    *,
    label_selector: str | None = None,
    field_selector: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    query: list[tuple[str, Any]] = [("limit", limit)]
    if label_selector:
        query.append(("labelSelector", label_selector))
    if field_selector:
        query.append(("fieldSelector", field_selector))
    what = f"{kind.plural}" + (f" in {namespace}" if kind.namespaced and namespace else "")
    status, data = await request("GET", kind.path(namespace), query=query)
    if status >= 400:
        raise api_error(status, data, what)
    return list(data.get("items") or [])


async def get_object(kind: Kind, namespace: str | None, name: str) -> dict[str, Any] | None:
    """The object, or None when it doesn't exist."""
    status, data = await request("GET", kind.path(namespace, name))
    if status == 404:
        return None
    if status >= 400:
        raise api_error(status, data, f"{kind.kind} {name}")
    return data


def clean(obj: dict[str, Any]) -> dict[str, Any]:
    """Drop what is noise to a human or a model: managed fields, the
    last-applied copy of the whole object, server bookkeeping."""
    obj = json.loads(json.dumps(obj))  # deep copy
    meta = obj.get("metadata") or {}
    for key in ("managedFields", "resourceVersion", "uid", "generation", "selfLink"):
        meta.pop(key, None)
    annotations = meta.get("annotations") or {}
    annotations.pop("kubectl.kubernetes.io/last-applied-configuration", None)
    annotations.pop("deployment.kubernetes.io/revision", None)
    if not annotations:
        meta.pop("annotations", None)
    return obj


__all__ = [
    "BLOCKED_KINDS",
    "KINDS",
    "Kind",
    "api_error",
    "clean",
    "get_json",
    "get_object",
    "is_blocked",
    "list_objects",
    "list_secret_metadata",
    "request",
    "resolve_kind",
]
