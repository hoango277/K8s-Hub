"""Kubernetes API client (read-only use) - kubeconfig or in-cluster.

Configuration (read at startup, from .env):
  - K8S_IN_CLUSTER=true  -> the pod's ServiceAccount (when K8s-Hub runs on the cluster)
  - KUBECONFIG=<path>    -> a kubeconfig file (development machine)
  - neither              -> not configured; skills report that plainly

Give K8s-Hub a READ-ONLY identity (a ServiceAccount bound to the built-in
`view` ClusterRole). The skills here only read, but least privilege means a
bug or a prompt injection can't turn into a write even if someone adds one.

API clients are built per call rather than cached: the calls are rare
(one per tool invocation) and a cached client would outlive a kubeconfig
change or a token rotation.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from app.core.config import get_settings


class K8sError(RuntimeError):
    """Not configured, unreachable, forbidden or not found. Message is user-facing."""


def config_problem() -> str | None:
    """Why the cluster can't be reached, or None when it is configured."""
    config = get_settings()
    if config.K8S_IN_CLUSTER or (config.KUBECONFIG or "").strip():
        return None
    return (
        "No Kubernetes access is configured (set KUBECONFIG, or K8S_IN_CLUSTER=true "
        "when running on the cluster)."
    )


@asynccontextmanager
async def api_client():
    from kubernetes_asyncio import client, config

    problem = config_problem()
    if problem:
        raise K8sError(problem)
    settings = get_settings()
    try:
        if settings.K8S_IN_CLUSTER:
            config.load_incluster_config()
            api = client.ApiClient()
        else:
            cfg = client.Configuration()
            await config.load_kube_config(config_file=settings.KUBECONFIG, client_configuration=cfg)
            api = client.ApiClient(configuration=cfg)
    except Exception as exc:
        raise K8sError(f"Could not load the Kubernetes configuration: {exc}") from exc
    try:
        yield api
    finally:
        await api.close()


def _translate(exc: Exception, what: str) -> K8sError:
    status = getattr(exc, "status", None)
    if status == 404:
        return K8sError(f"{what} not found.")
    if status == 403:
        return K8sError(f"K8s-Hub is not allowed to read {what} (RBAC).")
    if status:
        return K8sError(f"The Kubernetes API returned {status} for {what}.")
    return K8sError(f"Could not reach the Kubernetes API: {type(exc).__name__}: {exc}")


async def list_pods(namespace: str, label_selector: str | None = None) -> list[Any]:
    from kubernetes_asyncio import client

    async with api_client() as api:
        try:
            resp = await client.CoreV1Api(api).list_namespaced_pod(
                namespace, label_selector=label_selector or None, limit=200
            )
        except Exception as exc:
            raise _translate(exc, f"pods in {namespace}") from exc
    return list(resp.items)


async def read_pod(namespace: str, name: str) -> Any:
    from kubernetes_asyncio import client

    async with api_client() as api:
        try:
            return await client.CoreV1Api(api).read_namespaced_pod(name, namespace)
        except Exception as exc:
            raise _translate(exc, f"pod {namespace}/{name}") from exc


async def list_events(namespace: str, *, involved_name: str | None = None) -> list[Any]:
    from kubernetes_asyncio import client

    selector = f"involvedObject.name={involved_name}" if involved_name else None
    async with api_client() as api:
        try:
            resp = await client.CoreV1Api(api).list_namespaced_event(
                namespace, field_selector=selector, limit=500
            )
        except Exception as exc:
            raise _translate(exc, f"events in {namespace}") from exc
    return list(resp.items)


async def pod_logs(
    namespace: str, name: str, *, container: str | None, previous: bool, tail_lines: int
) -> str:
    from kubernetes_asyncio import client

    async with api_client() as api:
        try:
            return await client.CoreV1Api(api).read_namespaced_pod_log(
                name,
                namespace,
                container=container or None,
                previous=previous,
                tail_lines=tail_lines,
                timestamps=True,
            )
        except Exception as exc:
            raise _translate(exc, f"logs of {namespace}/{name}") from exc


async def list_deployments(namespace: str) -> list[Any]:
    from kubernetes_asyncio import client

    async with api_client() as api:
        try:
            resp = await client.AppsV1Api(api).list_namespaced_deployment(namespace, limit=200)
        except Exception as exc:
            raise _translate(exc, f"deployments in {namespace}") from exc
    return list(resp.items)


async def check() -> dict[str, Any]:
    """For Settings > Connections: server version, proves auth works."""
    from kubernetes_asyncio import client

    async with api_client() as api:
        try:
            info = await client.VersionApi(api).get_code()
        except Exception as exc:
            raise _translate(exc, "the cluster version") from exc
    return {"version": info.git_version}


__all__ = [
    "K8sError",
    "check",
    "config_problem",
    "list_deployments",
    "list_events",
    "list_pods",
    "pod_logs",
    "read_pod",
]
