"""The labelled faults. Each one: a healthy setup, ONE fault, and the ground truth.

Fault types follow the usual chaos-engineering taxonomy (bad deploy, resource
exhaustion, misconfiguration, scheduling, storage, human operation) — the same
families RCAEval / Chaos Mesh use — but they run on a live cluster, because
K8s-Hub diagnoses live state (API objects, events, rollouts), which offline
telemetry datasets don't contain.

Ground truth = the event TYPES that name the real root cause, and the entity
it happened to. Every workload requests 5m CPU: lab1's node is ~96% requested.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from rca_eval import lab

SMALL = {"requests": {"cpu": "5m", "memory": "16Mi"}, "limits": {"memory": "64Mi"}}


def deployment(
    name: str,
    image: str,
    *,
    command: list[str] | None = None,
    env: list[dict] | None = None,
    env_from: list[dict] | None = None,
    resources: dict | None = None,
    readiness: dict | None = None,
    volumes: list[dict] | None = None,
    mounts: list[dict] | None = None,
    recreate: bool = False,
) -> dict[str, Any]:
    container: dict[str, Any] = {"name": name, "image": image, "resources": resources or SMALL}
    for key, value in (
        ("command", command), ("env", env), ("envFrom", env_from),
        ("readinessProbe", readiness), ("volumeMounts", mounts),
    ):  # fmt: skip
        if value:
            container[key] = value
    spec: dict[str, Any] = {
        "replicas": 1,
        "selector": {"matchLabels": {"app": name}},
        "template": {
            "metadata": {"labels": {"app": name}},
            "spec": {"containers": [container], "terminationGracePeriodSeconds": 2},
        },
    }
    if volumes:
        spec["template"]["spec"]["volumes"] = volumes
    if recreate:
        spec["strategy"] = {"type": "Recreate"}
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name}, "spec": spec}


def service(name: str) -> dict[str, Any]:
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {"selector": {"app": name}, "ports": [{"port": 80}]},
    }


def configmap(name: str, data: dict[str, str]) -> dict[str, Any]:
    return {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": name}, "data": data}


def manifest(*objects: dict[str, Any]) -> str:
    return json.dumps({"apiVersion": "v1", "kind": "List", "items": list(objects)})


SLEEP = ["sh", "-c", "sleep 36000"]
NGINX = "nginx:1.27-alpine"
BUSYBOX = "busybox:1.36"


@dataclass
class Scenario:
    id: str
    title: str
    # Healthy starting point and the deployments to wait for.
    setup: list[dict[str, Any]]
    ready: list[str]
    fault: Callable[[], Awaitable[None]]
    # Ground truth: the root cause is an event of one of these types on this entity.
    expect_types: set[str]
    expect_entity: str
    # The diagnosis (and the baseline question) focus on this workload, like an alert would.
    target: str
    # How long symptoms need to show up after the fault.
    wait_seconds: int
    # Baseline grading: the LLM-only answer is correct if its ROOT CAUSE line matches one.
    keywords: list[str] = field(default_factory=list)


async def _set_image() -> None:
    await lab.kubectl("set", "image", "deployment/web", "web=nginx:9.99.99-does-not-exist")


async def _oom() -> None:
    hog = deployment(
        "hog",
        "polinux/stress:1.0.4",
        command=["stress", "--vm", "1", "--vm-bytes", "200M", "--vm-hang", "0"],
        resources={"requests": {"cpu": "5m", "memory": "32Mi"}, "limits": {"memory": "96Mi"}},
    )
    await lab.apply(manifest(hog))


async def _bad_config() -> None:
    await lab.kubectl("patch", "configmap", "app-config", "--type=merge", "-p",
                      json.dumps({"data": {"MODE": "broken"}}))  # fmt: skip
    # Pods read env at start: the edit bites when a pod is replaced (eviction,
    # node restart…). Deleting the pod does that without a rollout.
    await lab.kubectl("delete", "pod", "-l", "app=cfg", "--wait=false")


async def _missing_key() -> None:
    patch = [{
        "op": "replace",
        "path": "/spec/template/spec/containers/0/env/0/valueFrom/configMapKeyRef/key",
        "value": "KEY_MISSING",
    }]  # fmt: skip
    await lab.kubectl("patch", "deployment", "keys", "--type=json", "-p", json.dumps(patch))


async def _bad_probe() -> None:
    patch = {"spec": {"template": {"spec": {"containers": [
        {"name": "api", "readinessProbe": {"httpGet": {"path": "/does-not-exist", "port": 80},
                                           "periodSeconds": 5}},
    ]}}}}  # fmt: skip
    await lab.kubectl("patch", "deployment", "api", "--type=strategic", "-p", json.dumps(patch))


async def _too_big() -> None:
    await lab.kubectl("set", "resources", "deployment/big", "--requests=cpu=16")


async def _pvc() -> None:
    pvc = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {"name": "data"},
        "spec": {
            "storageClassName": "rca-lab-missing-class",
            "accessModes": ["ReadWriteOnce"],
            "resources": {"requests": {"storage": "1Gi"}},
        },
    }
    store = deployment(
        "store", BUSYBOX, command=SLEEP,
        volumes=[{"name": "data", "persistentVolumeClaim": {"claimName": "data"}}],
        mounts=[{"name": "data", "mountPath": "/data"}],
    )  # fmt: skip
    await lab.apply(manifest(pvc, store))


async def _scale_zero_via_approval() -> None:
    """The fault is a change applied THROUGH K8s-Hub: propose + approve, like an engineer would."""
    from app.db.session import get_sessionmaker
    from app.modules.nl_command import planner
    from app.services import approval_service as svc

    actor = svc.Actor(id=None, email="rca-eval@k8s-hub", role="admin")
    plan = await planner.plan_scale("deployment", lab.NAMESPACE, "api2", 0)
    row = await svc.propose(
        plan, actor=actor, source="rca-eval", request_text="RCA evaluation: scale api2 to zero"
    )
    if row.status == "pending":
        async with get_sessionmaker()() as db:
            await svc.approve(db, row.id, actor)


SCENARIOS: list[Scenario] = [
    Scenario(
        "bad-image", "Rollout to an image tag that doesn't exist",
        setup=[deployment("web", NGINX)], ready=["web"], fault=_set_image,
        expect_types={"Rollout"}, expect_entity="web", target="web", wait_seconds=90,
        keywords=[r"image", r"tag", r"pull"],
    ),
    Scenario(
        "oom", "Container allocates more memory than its limit",
        setup=[], ready=[], fault=_oom,
        expect_types={"MemoryNearLimit", "OOMKilled"}, expect_entity="hog", target="hog",
        wait_seconds=150, keywords=[r"oom", r"out of memory", r"memory limit"],
    ),
    Scenario(
        "bad-config", "ConfigMap edited to a value the app refuses",
        setup=[
            configmap("app-config", {"MODE": "ok"}),
            deployment("cfg", BUSYBOX, env_from=[{"configMapRef": {"name": "app-config"}}],
                       command=["sh", "-c", 'if [ "$MODE" != ok ]; then echo "fatal: unsupported '
                                'MODE=$MODE" >&2; exit 1; fi; sleep 36000']),
        ],
        ready=["cfg"], fault=_bad_config,
        expect_types={"ConfigChange"}, expect_entity="app-config", target="cfg", wait_seconds=120,
        keywords=[r"configmap", r"app-config", r"\bMODE\b"],
    ),
    Scenario(
        "missing-key", "Rollout references a ConfigMap key that doesn't exist",
        setup=[
            configmap("keys-config", {"KEY_A": "1"}),
            deployment("keys", BUSYBOX, command=SLEEP, env=[{"name": "A", "valueFrom": {
                "configMapKeyRef": {"name": "keys-config", "key": "KEY_A"}}}]),
        ],
        ready=["keys"], fault=_missing_key,
        expect_types={"Rollout"}, expect_entity="keys", target="keys", wait_seconds=90,
        keywords=[r"KEY_MISSING", r"missing key", r"couldn't find key", r"configMapKeyRef"],
    ),
    Scenario(
        "bad-probe", "Rollout with a readiness probe on a path that 404s",
        setup=[
            deployment("api", NGINX, recreate=True,
                       readiness={"httpGet": {"path": "/", "port": 80}, "periodSeconds": 5}),
            service("api"),
        ],
        ready=["api"], fault=_bad_probe,
        expect_types={"Rollout"}, expect_entity="api", target="api", wait_seconds=120,
        keywords=[r"readiness", r"probe"],
    ),
    Scenario(
        "too-big", "Rollout requests more CPU than the node has",
        setup=[deployment("big", BUSYBOX, command=SLEEP)], ready=["big"], fault=_too_big,
        expect_types={"Rollout"}, expect_entity="big", target="big", wait_seconds=90,
        keywords=[r"insufficient cpu", r"cpu.{0,40}request", r"request.{0,40}cpu"],
    ),
    Scenario(
        "pvc-pending", "Volume claim with a storage class that doesn't exist",
        setup=[], ready=[], fault=_pvc,
        expect_types={"PvcPending"}, expect_entity="data", target="store", wait_seconds=120,
        keywords=[r"storage ?class", r"persistentvolumeclaim", r"\bpvc\b", r"unbound"],
    ),
    Scenario(
        "scale-zero", "Approved change through K8s-Hub scales the backend to 0",
        setup=[deployment("api2", NGINX), service("api2")], ready=["api2"],
        fault=_scale_zero_via_approval,
        expect_types={"ApprovalExecuted", "ScaleChange"}, expect_entity="api2", target="api2",
        wait_seconds=60,
        keywords=[r"scal\w* (down )?to (0|zero)", r"\b0 replicas", r"replicas:? ?0"],
    ),
]  # fmt: skip

BY_ID = {s.id: s for s in SCENARIOS}

__all__ = ["BY_ID", "SCENARIOS", "Scenario", "manifest"]
