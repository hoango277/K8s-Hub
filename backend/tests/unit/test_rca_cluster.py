"""RCA improvements of 08/10/2026: whole-cluster topology, dependencies from every source,
more change sources, better anomaly detection. No cluster, no network."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from app.integrations.k8s import resources as res
from app.integrations.loki.client import LogLine  # noqa: F401  (shape reference)
from app.modules.rca import causality, ranking, topology
from app.modules.rca.detectors import (
    Context,
    Found,
    change_point,
    changes,
    dependencies,
    linear_trend,
    metrics,
    pods,
)
from app.modules.rca.detectors.logs import dependencies_from_lines
from app.modules.rca.snapshot import Snapshot

T0 = datetime(2026, 10, 8, 10, 0, tzinfo=UTC)


def iso(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def deploy(ns: str, name: str, env: list | None = None, annotations: dict | None = None) -> dict:
    return {
        "metadata": {"name": name, "namespace": ns, "annotations": annotations or {}},
        "spec": {
            "template": {
                "metadata": {"labels": {"app": name}},
                "spec": {"containers": [{"name": name, "image": f"{name}:1", "env": env or []}]},
            }
        },
    }


def statefulset(ns: str, name: str) -> dict:
    return {
        "metadata": {"name": name, "namespace": ns},
        "spec": {"template": {"metadata": {"labels": {"app": name}}, "spec": {"containers": []}}},
    }


def service(ns: str, name: str, app: str) -> dict:
    return {"metadata": {"name": name, "namespace": ns}, "spec": {"selector": {"app": app}}}


def pod(ns: str, name: str, app: str, owner_kind: str, owner: str) -> dict:
    return {
        "metadata": {
            "name": name,
            "namespace": ns,
            "labels": {"app": app},
            "ownerReferences": [{"kind": owner_kind, "name": owner}],
        },
        "spec": {"containers": [{"name": app}]},
        "status": {"phase": "Running"},
    }


def langfuse_and_database() -> Snapshot:
    """langfuse-worker (ns langfuse) reads its database host from env; the database
    is StatefulSet `pg` behind Service `pg-rw` in ns `database`."""
    snap = Snapshot(T0)
    worker_env = [
        {"name": "DATABASE_HOST", "value": "pg-rw.database.svc.cluster.local"},
        {"name": "DATABASE_NAME", "value": "langfuse"},  # a word, not a host
        {"name": "REDIS_CONNECTION_STRING", "value": "redis://default:x@langfuse-redis:6379/0"},
        {"name": "DATABASE_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "db", "key": "pw"}}},
    ]
    snap.deployments = [
        deploy("langfuse", "langfuse-worker", worker_env),
        deploy("langfuse", "langfuse-redis"),
        deploy("langfuse", "langfuse"),
    ]
    snap.statefulsets = [statefulset("database", "pg")]
    snap.replicasets = [
        {
            "metadata": {
                "name": "langfuse-worker-59fd",
                "namespace": "langfuse",
                "ownerReferences": [{"kind": "Deployment", "name": "langfuse-worker"}],
            }
        }
    ]
    snap.services = [
        service("database", "pg-rw", "pg"),
        service("langfuse", "langfuse-redis", "langfuse-redis"),
        service("langfuse", "langfuse", "langfuse"),
    ]
    snap.pods = [
        pod("langfuse", "langfuse-worker-59fd-abc", "langfuse-worker", "ReplicaSet",
            "langfuse-worker-59fd"),
        pod("database", "pg-1", "pg", "StatefulSet", "pg"),
    ]  # fmt: skip
    return snap


# --- hosts -----------------------------------------------------------------------------


def test_candidate_hosts_and_resolution():
    topo = topology.build(langfuse_and_database())
    hosts = topology.candidate_hosts("postgres://u:p@pg-rw.database.svc:5432/db")
    assert "pg-rw.database.svc" in hosts
    resolve = topo.resolve_host
    assert resolve("pg-rw.database.svc.cluster.local", "langfuse").key == "Service/database/pg-rw"
    assert resolve("pg-rw.database", "langfuse").key == "Service/database/pg-rw"
    assert resolve("pg-1.pg-rw.database.svc", "x").key == "Service/database/pg-rw"
    assert resolve("langfuse-redis", "langfuse").key == "Service/langfuse/langfuse-redis"
    assert resolve("example.com", "langfuse") is None
    # A bare word only counts as a host when the variable names a host.
    assert topology.candidate_hosts("langfuse", "DATABASE_NAME") == set()
    assert topology.candidate_hosts("langfuse-redis", "REDIS_HOST") == {"langfuse-redis"}


def test_config_dependencies_cross_namespace():
    topo = topology.build(langfuse_and_database())
    deps = {(c, d): s for (c, d), s in topo.dependencies.items()}
    worker = "Workload/langfuse/langfuse-worker"
    assert deps[(worker, "Service/database/pg-rw")] == {"config"}
    assert (worker, "Service/langfuse/langfuse-redis") in deps
    # DATABASE_NAME=langfuse must not "call" the Service named langfuse.
    assert (worker, "Service/langfuse/langfuse") not in deps
    # The Service's backend workload, in the other namespace, is a callee too.
    callees = {
        e.key for e in topo.related(topology.workload("langfuse", "langfuse-worker"), "callee")
    }
    assert "Workload/database/pg" in callees
    assert topo.dependency_namespaces({"langfuse"}) == {"langfuse", "database"}


def test_annotation_with_namespace_prefix():
    snap = langfuse_and_database()
    snap.deployments.append(
        deploy("shop", "web", annotations={topology.DEPENDS_ON_ANNOTATION: "database/pg-rw"})
    )
    topo = topology.build(snap)
    assert topo.dependencies[("Workload/shop/web", "Service/database/pg-rw")] == {"annotation"}


def test_metric_dependencies_from_beyla_client_metrics():
    topo = topology.build(langfuse_and_database())
    rows = [
        {"metric": {"k8s_namespace_name": "langfuse", "k8s_deployment_name": "langfuse-worker",
                    "server_address": "pg-rw.database.svc.cluster.local"}},
        {"metric": {"k8s_namespace_name": "langfuse", "k8s_deployment_name": "nope",
                    "server_address": "pg-rw.database"}},  # unknown caller
        {"metric": {"k8s_namespace_name": "langfuse", "k8s_deployment_name": "langfuse",
                    "server_address": "api.github.com"}},  # external
    ]  # fmt: skip
    assert dependencies.add_metric_dependencies(topo, rows) == 1
    sources = topo.dependencies[("Workload/langfuse/langfuse-worker", "Service/database/pg-rw")]
    assert sources == {"config", "metric"}


def test_log_dependencies_from_error_lines():
    snap = langfuse_and_database()
    snap.deployments[0]["spec"]["template"]["spec"]["containers"][0]["env"] = []  # no config hint
    topo = topology.build(snap)
    ctx = Context(snap, topo, [], T0 - timedelta(hours=1), T0)
    added = dependencies_from_lines(
        ctx,
        "langfuse",
        "langfuse-worker-59fd-abc",
        ["Error: connect ECONNREFUSED pg-rw.database.svc.cluster.local:5432"],
    )
    assert added == 1
    assert ("Workload/langfuse/langfuse-worker", "Service/database/pg-rw") in topo.dependencies


# --- failures travelling along dependencies ------------------------------------------------


def test_database_crash_explains_caller_crash_across_namespaces():
    topo = topology.build(langfuse_and_database())
    f = Found()
    db_pod = topo.ensure_pod("database", "pg-1")
    worker_pod = topo.ensure_pod("langfuse", "langfuse-worker-59fd-abc")
    f.add("OOMKilled", db_pod, T0 - timedelta(minutes=10), "pg OOM-killed")
    f.add("CrashLoop", db_pod, T0 - timedelta(minutes=9), "pg crash-looping", exit_code=137)
    f.add("CrashLoop", worker_pod, T0 - timedelta(minutes=8), "worker crash-looping")
    graph, _ = causality.build(f.all(), topo, T0 - timedelta(hours=1), focus={"langfuse"})
    # The diagnosis is about langfuse: its symptom is the starting point…
    assert graph.seeds == ["CrashLoop:Pod/langfuse/langfuse-worker-59fd-abc"]
    assert any(e.rule == "dep-crashloop-crashloop" for e in graph.edges)
    hyps = ranking.rank(graph)
    # …and the root cause is found in the database namespace.
    assert graph.events[hyps[0].event_id].entity.namespace == "database"


def test_scope_limits_what_detectors_read():
    snap = langfuse_and_database()
    snap.pods[1]["status"] = {
        "phase": "Running",
        "containerStatuses": [{"name": "pg", "restartCount": 3,
                               "state": {"waiting": {"reason": "CrashLoopBackOff"}}}],
    }  # fmt: skip
    topo = topology.build(snap)
    only_langfuse = Context(snap, topo, [], T0 - timedelta(hours=1), T0, namespaces={"langfuse"})
    found = Found()
    asyncio.run(pods.detect(only_langfuse, found))
    assert not found.events  # the crashing pod is in `database`, outside the scope
    everything = Context(snap, topo, [], T0 - timedelta(hours=1), T0, namespaces=None)
    asyncio.run(pods.detect(everything, found))
    assert "CrashLoop:Pod/database/pg-1" in found.events


# --- more change sources ---------------------------------------------------------------------


def run_changes(snap: Snapshot) -> Found:
    topo = topology.build(snap)
    ctx = Context(snap, topo, [], T0 - timedelta(hours=1), T0 + timedelta(minutes=5))
    found = Found()
    asyncio.run(changes.detect(ctx, found))
    return found


def test_statefulset_rollout_from_controller_revisions():
    snap = langfuse_and_database()

    def rev(n: int, image: str, minutes: float) -> dict:
        containers = [{"name": "pg", "image": image}]
        return {
            "metadata": {
                "name": f"pg-{n}",
                "namespace": "database",
                "creationTimestamp": iso(minutes),
                "ownerReferences": [{"kind": "StatefulSet", "name": "pg"}],
            },
            "revision": n,
            "data": {"spec": {"template": {"spec": {"containers": containers}}}},
        }

    snap.controllerrevisions = [rev(1, "postgres:16", -500), rev(2, "postgres:17", -5)]
    ev = run_changes(snap).events["Rollout:Workload/database/pg"]
    assert ev.attrs["images"] == {"pg": ["postgres:16", "postgres:17"]}
    assert ev.entity.sub == "StatefulSet"


def test_argocd_sync_marks_the_workloads_it_deployed():
    snap = langfuse_and_database()
    snap.argocd_apps = [
        {
            "metadata": {"name": "langfuse", "namespace": "argocd"},
            "status": {
                "history": [
                    {"revision": "abc123def4567", "deployedAt": iso(-300)},
                    {"revision": "fedcba9876543", "deployedAt": iso(-4)},
                ],
                "resources": [
                    {"kind": "Deployment", "namespace": "langfuse", "name": "langfuse-worker"},
                    {"kind": "Service", "namespace": "langfuse", "name": "langfuse"},
                ],
            },
        }
    ]
    found = run_changes(snap)
    ev = found.events["GitOpsSync:Workload/langfuse/langfuse-worker"]
    assert ev.attrs["revision"] == "fedcba987654" and ev.attrs["application"] == "langfuse"
    assert not any(k.startswith("GitOpsSync:Service") for k in found.events)


def test_helm_upgrade_from_release_metadata():
    snap = langfuse_and_database()
    snap.deployments[0]["metadata"]["annotations"] = {
        changes.HELM_RELEASE: "langfuse",
        changes.HELM_NAMESPACE: "langfuse",
    }
    snap.secret_metadata = [
        {"metadata": {"name": "sh.helm.release.v1.langfuse.v6", "namespace": "langfuse",
                      "labels": {"owner": "helm", "name": "langfuse", "version": "6",
                                 "status": "superseded"}, "creationTimestamp": iso(-600)}},
        {"metadata": {"name": "sh.helm.release.v1.langfuse.v7", "namespace": "langfuse",
                      "labels": {"owner": "helm", "name": "langfuse", "version": "7",
                                 "status": "deployed"}, "creationTimestamp": iso(-3)}},
    ]  # fmt: skip
    ev = run_changes(snap).events["HelmRelease:Workload/langfuse/langfuse-worker"]
    assert ev.attrs["version"] == 7 and ev.prior == ev.kind.prior  # an upgrade, not an install


def test_secret_change_only_for_secrets_pods_use_and_created_is_weaker():
    snap = langfuse_and_database()
    snap.pods[0]["spec"]["containers"][0]["env"] = [
        {"name": "PW", "valueFrom": {"secretKeyRef": {"name": "db", "key": "pw"}}}
    ]
    snap.secret_metadata = [
        {"metadata": {"name": "db", "namespace": "langfuse", "labels": {},
                      "creationTimestamp": iso(-5000),
                      "managedFields": [{"manager": "kubectl", "time": iso(-2)}]}},
        {"metadata": {"name": "unused", "namespace": "langfuse", "labels": {},
                      "creationTimestamp": iso(-5000),
                      "managedFields": [{"manager": "kubectl", "time": iso(-2)}]}},
    ]  # fmt: skip
    found = run_changes(snap)
    ev = found.events["SecretChange:Secret/langfuse/db"]
    assert ev.attrs["how"] == "edited" and "kubectl" in ev.evidence[0].text
    assert "SecretChange:Secret/langfuse/unused" not in found.events


def test_secret_metadata_never_returns_values(monkeypatch):
    """Even if a server ignored the metadata-only media type, values and the
    last-applied annotation (which holds the whole Secret) are dropped."""
    full = {
        "items": [
            {
                "metadata": {
                    "name": "db",
                    "namespace": "x",
                    "labels": {"a": "b"},
                    "annotations": {"kubectl.kubernetes.io/last-applied-configuration": "{pw}"},
                    "managedFields": [
                        {"manager": "kubectl", "time": "t", "fieldsV1": {"f:data": {}}}
                    ],
                },
                "data": {"pw": "c2VjcmV0"},
            }
        ]
    }
    seen = {}

    async def fake_request(method, path, *, query=None, accept="application/json", **_):
        seen["accept"] = accept
        return 200, full

    monkeypatch.setattr(res, "request", fake_request)
    (item,) = asyncio.run(res.list_secret_metadata())
    assert "PartialObjectMetadataList" in seen["accept"]
    assert "data" not in item and "annotations" not in item["metadata"]
    assert item["metadata"]["managedFields"] == [
        {"manager": "kubectl", "operation": None, "time": "t"}
    ]


# --- anomaly detection -------------------------------------------------------------------------


def test_change_point_finds_where_the_level_moves():
    early = [(float(i), 1.0 if i < 3 else 20.0) for i in range(30)]  # change at index 3
    hit = change_point(early, min_absolute=5)
    assert hit is not None and hit[0] == 3
    noisy_flat = [(float(i), 5.0 + (i % 3)) for i in range(30)]
    assert change_point(noisy_flat, min_absolute=5) is None


def test_memory_leak_trend():
    points = [(t * 60.0, 0.60 + 0.004 * t) for t in range(30)]  # +24%/h, now ~72%
    slope, r2 = linear_trend(points)
    assert slope > 0 and r2 > 0.99
    found = Found()
    metrics._leak(found, topology.workload("x", "w"), "app", points)
    (ev,) = found.events.values()
    assert ev.type == "MemoryLeak" and ev.attrs["growth_per_hour"] > 0.2


def test_metric_address_matched_by_unique_prefix_only():
    snap = langfuse_and_database()
    snap.services.append(service("langfuse", "langfuse-clickhouse-headless", "langfuse-clickhouse"))
    topo = topology.build(snap)
    assert topo.resolve_host("langfuse-clickhouse", "langfuse") is None  # exact only by default
    hit = topo.resolve_host("langfuse-clickhouse", "langfuse", by_prefix=True)
    assert hit.key == "Service/langfuse/langfuse-clickhouse-headless"
    # `langfuse` prefixes langfuse-redis AND langfuse-clickhouse-headless: ambiguous, no edge.
    snap2 = langfuse_and_database()
    snap2.services = [s for s in snap2.services if s["metadata"]["name"] != "langfuse"]
    snap2.services.append(service("langfuse", "langfuse-clickhouse-headless", "x"))
    topo2 = topology.build(snap2)
    assert topo2.resolve_host("langfuse", "langfuse", by_prefix=True) is None


def test_idle_service_without_backends_is_not_a_symptom():
    from app.modules.rca.detectors import workloads

    snap = langfuse_and_database()
    # pg-ro: selects replica pods that don't exist; nobody calls it; nothing behind it.
    snap.services.append(service("database", "pg-ro", "pg-replica"))
    snap.endpoints = [
        {"metadata": {"name": "pg-ro", "namespace": "database"}, "subsets": []},
        {"metadata": {"name": "pg-rw", "namespace": "database"}, "subsets": []},
    ]
    topo = topology.build(snap)
    ctx = Context(snap, topo, [], T0 - timedelta(hours=1), T0)
    found = Found()
    asyncio.run(workloads.detect(ctx, found))
    assert "ServiceNoEndpoints:Service/database/pg-ro" not in found.events
    # pg-rw is called by langfuse-worker: losing its endpoints IS a symptom.
    assert "ServiceNoEndpoints:Service/database/pg-rw" in found.events


# --- learning from feedback -------------------------------------------------------------------


def test_feedback_factor_is_smoothed_and_clamped():
    from app.modules.rca.learning import factor

    assert factor(0, 0) == 1.0
    assert 1.4 < factor(3, 0) < 1.5 and 0.5 < factor(0, 3) < 0.6
    assert factor(100, 0) == 1.5 and factor(0, 100) == 0.5  # never overturns the rules


def test_learned_weights_change_the_ranking():
    from app.modules.rca.learning import Weights
    from app.modules.rca.model import Entity

    topo = topology.build(langfuse_and_database())
    f = Found()
    # Two equally plausible changes, same time: a ConfigMap edit and a Secret edit.
    f.add("ConfigChange", Entity("ConfigMap", "langfuse", "a"), T0, "edited")
    f.add("SecretChange", Entity("Secret", "langfuse", "b"), T0, "edited")
    graph, _ = causality.build(f.all(), topo, T0 - timedelta(hours=1))
    before = ranking.rank(graph)[0].event_id
    assert before.startswith("ConfigChange")  # higher hand-set prior (0.95 vs 0.9)
    # Engineers kept marking Secret changes right and ConfigMap edits wrong.
    learned = Weights({"type:SecretChange": 1.5, "type:ConfigChange": 0.6})
    after = ranking.rank(graph, weights=learned)[0].event_id
    assert after.startswith("SecretChange")
