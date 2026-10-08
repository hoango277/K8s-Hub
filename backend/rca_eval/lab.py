"""kubectl helpers for the evaluation lab. Every command is pinned to the lab namespace.

kubectl (not the backend's own client) on purpose: the scenarios are what a
person would type, and the fault must not go through the code being evaluated.
"""

from __future__ import annotations

import asyncio
import json

NAMESPACE = "rca-lab"
# Kinds a scenario may create; cleanup deletes all of them (never the namespace,
# which holds the alert rules and the Alertmanager receiver).
CLEANUP_KINDS = "deployments,replicasets,services,configmaps,persistentvolumeclaims,pods"


class LabError(RuntimeError):
    pass


async def kubectl(*args: str, stdin: str | None = None, check: bool = True) -> str:
    proc = await asyncio.create_subprocess_exec(
        "kubectl", "-n", NAMESPACE, *args,
        stdin=asyncio.subprocess.PIPE if stdin is not None else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )  # fmt: skip
    out, err = await proc.communicate(stdin.encode() if stdin is not None else None)
    if check and proc.returncode != 0:
        raise LabError(f"kubectl {' '.join(args)}: {err.decode().strip() or out.decode().strip()}")
    return out.decode()


async def apply(manifest: str) -> None:
    await kubectl("apply", "-f", "-", stdin=manifest)


async def wait_ready(deployment: str, seconds: int = 180) -> None:
    await kubectl("rollout", "status", f"deployment/{deployment}", f"--timeout={seconds}s")


async def ensure_namespace() -> None:
    out = await kubectl("get", "namespace", NAMESPACE, "-o", "name", check=False)
    if not out.strip():
        raise LabError(
            f"Namespace {NAMESPACE} doesn't exist. Apply deploy/rca-lab/base.yaml first."
        )


async def cleanup() -> None:
    # The default ServiceAccount's ConfigMap (kube-root-ca.crt) is recreated by
    # Kubernetes right away; deleting it is harmless.
    await kubectl("delete", CLEANUP_KINDS, "--all", "--wait=true", "--timeout=120s", check=False)


async def pods(selector: str) -> list[dict]:
    out = await kubectl("get", "pods", "-l", selector, "-o", "json")
    return json.loads(out).get("items", [])


__all__ = ["NAMESPACE", "LabError", "apply", "cleanup", "ensure_namespace", "kubectl", "wait_ready"]
