"""Kubernetes API client (read-only use).

Nothing to configure in .env — the client finds its credentials the way
kubectl does:

  1. Inside a pod (how K8s-Hub is deployed): the pod's ServiceAccount, which
     Kubernetes mounts into every pod. No kubeconfig to copy around or protect;
     the token is rotated by Kubernetes and dies with the pod.
  2. Outside a pod (the backend run on a developer's machine): the SAME
     kubeconfig kubectl uses — the KUBECONFIG environment variable (several
     files separated by ";" on Windows, ":" elsewhere) or ~/.kube/config, with
     its current context. What `kubectl get pods` sees is what the tools see.
  3. Neither: the Kubernetes tools report themselves unavailable.

Mind the identity in case 2: it is whoever the kubeconfig belongs to — often a
cluster admin. The tools only read, but the deployed pod should use a
ServiceAccount bound to the `view` ClusterRole (read, no Secrets).

API clients are built per call rather than cached: calls are rare (one per
tool invocation), and a cached client would outlive a context switch or a
token rotation.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

TOKEN_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")


class K8sError(RuntimeError):
    """No credentials, unreachable, forbidden or not found. Message is user-facing."""


def _in_pod() -> bool:
    return bool(os.environ.get("KUBERNETES_SERVICE_HOST")) and TOKEN_FILE.is_file()


def _kubeconfig_files() -> list[Path]:
    """The kubeconfig files kubectl would read, that exist."""
    raw = os.environ.get("KUBECONFIG") or str(Path.home() / ".kube" / "config")
    return [
        Path(p).expanduser() for p in raw.split(os.pathsep) if p and Path(p).expanduser().is_file()
    ]


def config_problem() -> str | None:
    """Why the cluster can't be reached, or None when credentials were found."""
    if _in_pod() or _kubeconfig_files():
        return None
    return (
        "No Kubernetes credentials found: run K8s-Hub as a pod on the cluster, or give "
        "this machine a kubeconfig (KUBECONFIG or ~/.kube/config) like kubectl uses."
    )


async def _configuration() -> Any:
    from kubernetes_asyncio import client, config

    problem = config_problem()
    if problem:
        raise K8sError(problem)
    cfg = client.Configuration()
    try:
        if _in_pod():
            config.load_incluster_config(client_configuration=cfg)
        else:
            await config.load_kube_config(
                config_file=os.pathsep.join(str(p) for p in _kubeconfig_files()),
                client_configuration=cfg,
            )
    except Exception as exc:
        # Name the files read: the usual cause is a process started before
        # KUBECONFIG was set (Windows only passes env vars to NEW processes), so it
        # silently fell back to ~/.kube/config alone.
        files = ", ".join(str(p) for p in _kubeconfig_files())
        hint = "" if os.environ.get("KUBECONFIG") else (
            " KUBECONFIG is not set in the backend process; if you set it recently, "
            "restart the backend from a new terminal."
        )
        raise K8sError(
            f"Could not load the Kubernetes credentials from {files}: {exc}.{hint}"
        ) from exc
    return cfg


@asynccontextmanager
async def api_client():
    from kubernetes_asyncio import client

    api = client.ApiClient(configuration=await _configuration())
    try:
        yield api
    finally:
        await api.close()


@asynccontextmanager
async def ws_api_client():
    """Same credentials, over a websocket — what `exec` into a pod needs."""
    from kubernetes_asyncio.stream import WsApiClient

    api = WsApiClient(configuration=await _configuration())
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
    "api_client",
    "check",
    "config_problem",
    "list_deployments",
    "list_events",
    "list_pods",
    "pod_logs",
    "read_pod",
    "ws_api_client",
]
