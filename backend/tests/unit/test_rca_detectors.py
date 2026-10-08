"""RCA phase 1: event history parsing, topology, and the cluster-state detectors.

Everything here runs on hand-written Kubernetes objects — no cluster, no
Prometheus. The detectors that query telemetry (metrics/logs/traces) are
covered through their pure helpers (spike, new_templates).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

from app.integrations.loki.client import LogLine
from app.modules.rca import events_store, topology
from app.modules.rca.detectors import Context, Found, changes, pods, spike, workloads
from app.modules.rca.detectors.logs import new_templates
from app.modules.rca.snapshot import Snapshot

NS = "shop"
T0 = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)


_NAMESPACED_ATTRS = (
    "pods",
    "replicasets",
    "deployments",
    "statefulsets",
    "daemonsets",
    "controllerrevisions",
    "services",
    "endpoints",
    "ingresses",
    "pvcs",
    "configmaps",
    "hpas",
)


def namespaced(snap: Snapshot, ns: str = NS) -> Snapshot:
    """Fixtures are written without metadata.namespace: put them all in `ns`."""
    for attr in _NAMESPACED_ATTRS:
        for obj in getattr(snap, attr):
            obj.setdefault("metadata", {}).setdefault("namespace", ns)
    return snap


def iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def rs(name: str, deploy: str, revision: int, created: float, image: str, env=None) -> dict:
    return {
        "metadata": {
            "name": name,
            "creationTimestamp": iso(created),
            "annotations": {changes.REVISION: str(revision)},
            "ownerReferences": [{"kind": "Deployment", "name": deploy}],
        },
        "spec": {
            "template": {
                "metadata": {"labels": {"app": deploy}},
                "spec": {"containers": [{"name": "app", "image": image, "env": env or []}]},
            }
        },
    }


def deployment(name: str, replicas: int = 1, available: int = 1) -> dict:
    return {
        "metadata": {"name": name},
        "spec": {"replicas": replicas, "template": {"metadata": {"labels": {"app": name}}}},
        "status": {"availableReplicas": available},
    }


def pod(name: str, rs_name: str, app: str, **status) -> dict:
    return {
        "metadata": {
            "name": name,
            "labels": {"app": app},
            "ownerReferences": [{"kind": "ReplicaSet", "name": rs_name}],
        },
        "spec": {"nodeName": "lab1", "containers": [{"name": "app", "image": "api:2"}]},
        "status": {"phase": "Running", **status},
    }


def api_event(kind: str, name: str, reason: str, message: str, first: float, last=None, n=1):
    return {
        "type": "Warning" if reason not in ("ScalingReplicaSet",) else "Normal",
        "reason": reason,
        "message": message,
        "involvedObject": {"kind": kind, "name": name, "namespace": NS},
        "firstTimestamp": iso(first),
        "lastTimestamp": iso(first if last is None else last),
        "count": n,
    }


def run(snap: Snapshot, *detectors, start=-60.0, end=30.0, approvals=None) -> Found:
    topo = topology.build(namespaced(snap))
    kevents = [e for e in (events_store.from_api(o) for o in snap.events) if e]
    ctx = Context(
        snap,
        topo,
        kevents,
        T0 + timedelta(minutes=start),
        T0 + timedelta(minutes=end),
        approvals=approvals or [],
    )
    found = Found()
    for d in detectors:
        asyncio.run(d.detect(ctx, found))
    return found


# --- events_store -----------------------------------------------------------------


def test_api_event_keeps_first_and_last_occurrence():
    ev = events_store.from_api(api_event("Pod", "p", "BackOff", "Back-off", 1, last=9, n=40))
    assert ev and ev.count == 40
    assert ev.since == T0 + timedelta(minutes=1)
    assert ev.at == T0 + timedelta(minutes=9)


def test_loki_event_line_json_and_logfmt():
    ts = int((T0.timestamp()) * 1e9)
    as_json = LogLine(
        ts,
        {"namespace": NS},
        json.dumps(
            {
                "reason": "Unhealthy",
                "kind": "Pod",
                "name": "p",
                "type": "Warning",
                "msg": "Readiness probe failed",
            }
        ),
    )
    as_logfmt = LogLine(ts, {"namespace": NS}, 'kind=Pod name=p reason=Killing type=Normal msg="x"')
    garbage = LogLine(ts, {}, "not an event")
    a, b = events_store.from_loki(as_json), events_store.from_loki(as_logfmt)
    assert a and a.reason == "Unhealthy" and a.message == "Readiness probe failed"
    assert a.namespace == NS and a.at == T0 and a.source == "loki"
    assert b and b.reason == "Killing" and b.kind == "Pod"
    assert events_store.from_loki(garbage) is None


# --- topology -----------------------------------------------------------------------


def test_topology_links_pods_services_config_and_deleted_pods():
    snap = Snapshot(T0)
    snap.deployments = [deployment("api")]
    snap.replicasets = [rs("api-7d9f", "api", 2, -10, "api:2")]
    p = pod("api-7d9f-abcde", "api-7d9f", "api")
    p["spec"]["containers"][0]["envFrom"] = [{"configMapRef": {"name": "api-config"}}]
    snap.pods = [p]
    snap.services = [{"metadata": {"name": "api"}, "spec": {"selector": {"app": "api"}}}]
    topo = topology.build(namespaced(snap))

    pod_e = topo.entities[f"Pod/{NS}/api-7d9f-abcde"]
    assert {e.name for e in topo.related(pod_e, "owner")} == {"api"}
    assert {e.name for e in topo.related(pod_e, "config")} == {"api-config"}
    assert {e.kind for e in topo.related(pod_e, "node")} == {"Node"}
    svc = topo.entities[f"Service/{NS}/api"]
    assert {e.name for e in topo.related(svc, "backend_workloads")} == {"api"}

    # A pod seen only in event history still finds its Deployment by name.
    gone = topo.ensure_pod(NS, "api-7d9f-zzzzz")
    assert topo.pod_owner(gone) and topo.pod_owner(gone).name == "api"


def test_depends_on_annotation_adds_call_edges():
    snap = Snapshot(T0)
    web = deployment("web")
    web["metadata"]["annotations"] = {topology.DEPENDS_ON_ANNOTATION: "api, db"}
    snap.deployments = [web, deployment("api"), deployment("db")]
    topo = topology.build(namespaced(snap))
    callees = topo.related(topology.workload(NS, "web"), "callee")
    assert {e.name for e in callees} == {"api", "db"}


# --- pods ---------------------------------------------------------------------------


def test_crashloop_with_oom_last_state():
    snap = Snapshot(T0)
    snap.pods = [
        pod(
            "api-1-a",
            "api-1",
            "api",
            containerStatuses=[
                {
                    "name": "app",
                    "ready": False,
                    "restartCount": 7,
                    "state": {"waiting": {"reason": "CrashLoopBackOff"}},
                    "lastState": {
                        "terminated": {"reason": "OOMKilled", "exitCode": 137, "finishedAt": iso(5)}
                    },
                }
            ],
        )
    ]
    snap.events = [
        api_event("Pod", "api-1-a", "BackOff", "Back-off restarting failed container", 2, 20, 30)
    ]
    found = run(snap, pods)
    crash = found.events[f"CrashLoop:Pod/{NS}/api-1-a"]
    assert crash.start == T0 + timedelta(minutes=2)  # first BackOff, not the last one
    assert crash.attrs["exit_code"] == 137
    oom = found.events[f"OOMKilled:Pod/{NS}/api-1-a"]
    assert oom.start == T0 + timedelta(minutes=5)
    assert all(len(e.text) <= 300 for e in crash.evidence)


def test_image_pull_and_unschedulable():
    snap = Snapshot(T0)
    bad = pod(
        "api-2-b",
        "api-2",
        "api",
        containerStatuses=[
            {
                "name": "app",
                "state": {"waiting": {"reason": "ImagePullBackOff", "message": "not found"}},
            }
        ],
    )
    pending = pod("api-2-c", "api-2", "api")
    pending["status"] = {
        "phase": "Pending",
        "conditions": [
            {
                "type": "PodScheduled",
                "status": "False",
                "reason": "Unschedulable",
                "message": "0/1 nodes are available: 1 Insufficient cpu.",
                "lastTransitionTime": iso(3),
            }
        ],
    }
    snap.pods = [bad, pending]
    found = run(snap, pods)
    assert found.events[f"ImagePullError:Pod/{NS}/api-2-b"].attrs["image"] == "api:2"
    unsched = found.events[f"Unschedulable:Pod/{NS}/api-2-c"]
    assert "Insufficient cpu" in unsched.attrs["message"]


def test_probe_failure_from_events_of_a_deleted_pod():
    snap = Snapshot(T0)
    snap.deployments = [deployment("api")]
    snap.replicasets = [rs("api-3", "api", 3, -30, "api:3")]
    snap.events = [
        api_event("Pod", "api-3-gone1", "Unhealthy", "Readiness probe failed: HTTP 500", 4, 9, 12)
    ]
    found = run(snap, pods)
    ev = found.events[f"ProbeFailed:Pod/{NS}/api-3-gone1"]
    assert ev.attrs["probe"] == "readiness"
    assert ev.start == T0 + timedelta(minutes=4)


# --- workloads ----------------------------------------------------------------------


def test_service_without_ready_endpoints_and_pending_pvc():
    snap = Snapshot(T0)
    snap.services = [{"metadata": {"name": "api"}, "spec": {"selector": {"app": "api"}}}]
    snap.endpoints = [
        {"metadata": {"name": "api"}, "subsets": [{"notReadyAddresses": [{"ip": "10.0.0.1"}]}]}
    ]
    snap.pvcs = [
        {
            "metadata": {"name": "data", "creationTimestamp": iso(1)},
            "spec": {"storageClassName": "nope"},
            "status": {"phase": "Pending"},
        }
    ]
    snap.events = [
        api_event(
            "PersistentVolumeClaim",
            "data",
            "ProvisioningFailed",
            'storageclass "nope" not found',
            1,
        )
    ]
    found = run(snap, workloads)
    assert found.events[f"ServiceNoEndpoints:Service/{NS}/api"].attrs["not_ready"] == 1
    pvc = found.events[f"PvcPending:PVC/{NS}/data"]
    assert pvc.attrs["storage_class"] == "nope"
    assert any("not found" in e.text for e in pvc.evidence)


def test_deployment_missing_replicas():
    snap = Snapshot(T0)
    snap.deployments = [deployment("api", replicas=3, available=0)]
    found = run(snap, workloads)
    ev = found.events[f"ReplicasUnavailable:Workload/{NS}/api"]
    assert ev.severity == "critical" and ev.attrs["desired"] == 3


# --- changes ------------------------------------------------------------------------


def test_rollout_diff_names_changed_image_and_env_without_values():
    snap = Snapshot(T0)
    snap.deployments = [deployment("api")]
    snap.replicasets = [
        rs("api-1", "api", 1, -500, "api:1", env=[{"name": "DB_URL", "value": "secret-ish"}]),
        rs("api-2", "api", 2, -5, "api:2", env=[{"name": "DB_URL", "value": "changed"}]),
    ]
    found = run(snap, changes)
    ev = found.events[f"Rollout:Workload/{NS}/api"]
    assert ev.attrs["image_changed"] is True
    assert ev.attrs["images"] == {"app": ["api:1", "api:2"]}
    assert ev.attrs["env_changed"] == ["app.DB_URL"]
    assert ev.attrs["previous_images"] == {"app": "api:1"}
    assert not any("changed" in e.text.split("DB_URL")[-1] for e in ev.evidence)
    assert "secret-ish" not in json.dumps(ev.to_json())


def test_scale_of_newest_replicaset_is_a_change_but_rollout_scaling_is_not():
    snap = Snapshot(T0)
    snap.deployments = [deployment("api")]
    snap.replicasets = [rs("api-1", "api", 1, -500, "api:1"), rs("api-2", "api", 2, -40, "api:2")]
    snap.events = [
        # The rollout itself: new RS up, old RS down — not scale changes.
        api_event(
            "Deployment", "api", "ScalingReplicaSet", "Scaled up replica set api-2 from 0 to 1", -40
        ),
        api_event(
            "Deployment",
            "api",
            "ScalingReplicaSet",
            "Scaled down replica set api-1 from 1 to 0",
            -39,
        ),
        # Someone scales to zero later.
        api_event(
            "Deployment", "api", "ScalingReplicaSet", "Scaled down replica set api-2 from 1 to 0", 2
        ),
    ]
    found = run(snap, changes)
    scale = found.events[f"ScaleChange:Workload/{NS}/api"]
    assert scale.attrs["replicas"] == 0 and scale.start == T0 + timedelta(minutes=2)
    assert f"Rollout:Workload/{NS}/api" in found.events


def test_configmap_edit_and_executed_approval():
    snap = Snapshot(T0)
    snap.configmaps = [
        {
            "metadata": {
                "name": "api-config",
                "creationTimestamp": iso(-1000),
                "managedFields": [{"time": iso(-1000)}, {"time": iso(-3)}],
            },
            "data": {"LOG_LEVEL": "x"},
        },
        {"metadata": {"name": "old", "creationTimestamp": iso(-1000)}, "data": {}},
        # Edited too, but no pod reads it: it can't explain a symptom.
        {
            "metadata": {
                "name": "unused",
                "creationTimestamp": iso(-1000),
                "managedFields": [{"time": iso(-2)}],
            },
            "data": {},
        },
    ]
    app = pod("api-1-a", "api-1", "api")
    app["spec"]["containers"][0]["envFrom"] = [{"configMapRef": {"name": "api-config"}}]
    snap.pods = [app]
    approvals = [
        {
            "id": "a1",
            "kind": "scale",
            "title": "Scale Deployment api to 0",
            "namespace": NS,
            "target": "Deployment/api",
            "status": "executed",
            "executed_at": T0 + timedelta(minutes=1),
            "requested_by_email": "u@x",
            "decided_by_email": "admin@x",
        }
    ]
    found = run(snap, changes, approvals=approvals)
    cm = found.events[f"ConfigChange:ConfigMap/{NS}/api-config"]
    assert cm.attrs["how"] == "edited" and cm.start == T0 + timedelta(minutes=-3)
    assert f"ConfigChange:ConfigMap/{NS}/old" not in found.events
    assert f"ConfigChange:ConfigMap/{NS}/unused" not in found.events
    assert found.events[f"ApprovalExecuted:Workload/{NS}/api"].attrs["approval_id"] == "a1"


# --- telemetry helpers ----------------------------------------------------------------


def test_spike_needs_a_clear_jump_over_baseline():
    flat = [(float(i), 2.0) for i in range(20)]
    assert spike(flat) is None
    jump = flat[:12] + [(12.0, 30.0)] + flat[13:]
    hit = spike(jump, min_absolute=5)
    assert hit and hit[0] == 12 and hit[1] == 2.0


def test_new_templates_only_reports_errors_that_appeared_after_the_spike():
    old = [(float(i), f"ERROR cache miss for key {i}") for i in range(10)]
    new = [(100.0 + i, f"ERROR connection refused to db-{i}:5432") for i in range(5)]
    out = new_templates(old + new, since=100.0)
    assert len(out) == 1
    template, count = out[0]
    assert "connection refused" in template and count == 5


def test_first_replicaset_of_a_new_deployment_is_not_a_scale_change():
    snap = Snapshot(T0)
    snap.deployments = [deployment("store")]
    snap.replicasets = [rs("store-1", "store", 1, -2, "busybox")]
    snap.events = [
        api_event(
            "Deployment",
            "store",
            "ScalingReplicaSet",
            "Scaled up replica set store-1 from 0 to 1",
            -2,
        ),  # fmt: skip
    ]
    found = run(snap, changes)
    assert f"ScaleChange:Workload/{NS}/store" not in found.events
    assert f"Rollout:Workload/{NS}/store" not in found.events


def test_scale_down_soon_after_creation_is_still_a_change():
    """Evaluation 08/10/2026: a Deployment scaled to 0 two minutes after it was
    created lost its ScaleChange (taken for the rollout bringing its RS up)."""
    snap = Snapshot(T0)
    snap.deployments = [deployment("api2")]
    snap.replicasets = [rs("api2-1", "api2", 1, -3, "nginx")]
    snap.events = [
        api_event("Deployment", "api2", "ScalingReplicaSet",
                  "Scaled up replica set api2-1 from 0 to 1", -3),
        api_event("Deployment", "api2", "ScalingReplicaSet",
                  "Scaled down replica set api2-1 from 1 to 0", -1),
    ]  # fmt: skip
    found = run(snap, changes)
    scale = found.events[f"ScaleChange:Workload/{NS}/api2"]
    assert scale.attrs["replicas"] == 0 and scale.start == T0 + timedelta(minutes=-1)
