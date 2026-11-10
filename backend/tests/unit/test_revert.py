"""Reverting an executed change (app/modules/nl_command/revert.py, executor.snapshot).

A revert is a NEW proposal that takes the objects back to how they were just
before the change ran. These tests run on a fake cluster: what matters is that
the reverse plan is exact (the right count, image, object version), that a
Secret is never read, that what can't be undone says why, and that a revert
always waits for a human.
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS
from typing import Any

import pytest

from app.integrations.k8s import resources as res
from app.modules.nl_command import executor, planner, revert
from app.modules.nl_command.planner import ActionPlan, K8sOp
from app.services import approval_service

DEPLOY_PATH = "/apis/apps/v1/namespaces/shop/deployments/api"
CM_PATH = "/api/v1/namespaces/shop/configmaps/cfg"
SVC_PATH = "/api/v1/namespaces/shop/services/web"


def deployment(replicas: int = 1, image: str = "acme/api:1.0", generation: int = 2) -> dict:
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "api",
            "namespace": "shop",
            "uid": "u-1",
            "resourceVersion": "100",
            "generation": generation,
            "managedFields": [{"manager": "kubectl"}],
            "annotations": {"deployment.kubernetes.io/revision": "4", "team": "shop"},
        },
        "spec": {
            "replicas": replicas,
            "template": {"spec": {"containers": [{"name": "api", "image": image}]}},
        },
        "status": {"readyReplicas": replicas},
    }


@pytest.fixture
def cluster(monkeypatch):
    """Objects by API path; records every GET so a test can prove what was read."""
    objects: dict[str, dict] = {}
    reads: list[str] = []

    async def request(method, path, **_):
        assert method == "GET", "the revert planner only reads"
        reads.append(path)
        if path in objects:
            return 200, copy.deepcopy(objects[path])
        return 404, {"message": "not found"}

    async def get_object(kind, namespace, name):
        obj = objects.get(kind.path(namespace, name))
        return copy.deepcopy(obj) if obj else None

    async def list_objects(kind, namespace, **_):
        return []

    monkeypatch.setattr(res, "request", request)
    monkeypatch.setattr(res, "get_object", get_object)
    monkeypatch.setattr(res, "list_objects", list_objects)
    return NS(objects=objects, reads=reads)


def executed(kind: str, plan: ActionPlan, before: list[dict] | None, **extra: Any) -> NS:
    """An executed approval row, as approval_service leaves it."""
    return NS(
        id=uuid.UUID("abcd1234-0000-4000-8000-000000000001"),
        status="executed",
        kind=kind,
        plan=plan.to_json(),
        before_state=before,
        thread_id=uuid.uuid4(),
        **extra,
    )


# --------------------------------------------------------------------------
# Snapshot: what is kept, what is never read
# --------------------------------------------------------------------------


async def test_snapshot_keeps_a_writable_copy_and_never_reads_a_secret(cluster):
    cluster.objects[DEPLOY_PATH] = deployment()
    secret_path = "/api/v1/namespaces/shop/secrets/db"
    plan = ActionPlan(
        kind="apply",
        title="t",
        danger="caution",
        ops=[
            K8sOp("PATCH", DEPLOY_PATH, "Deployment", "api", "shop"),
            K8sOp("PATCH", secret_path, "Secret", "db", "shop"),
            K8sOp("PATCH", CM_PATH, "ConfigMap", "cfg", "shop"),
        ],
    )
    snaps = await executor.snapshot(plan)
    assert snaps is not None
    deploy, secret, cm = snaps

    assert deploy["existed"] is True
    obj = deploy["object"]
    assert "status" not in obj
    for key in ("uid", "resourceVersion", "generation", "managedFields"):
        assert key not in obj["metadata"]
    # The controller's revision is dropped; the user's own annotation stays.
    assert obj["metadata"]["annotations"] == {"team": "shop"}

    assert secret == {
        "kind": "Secret", "name": "db", "namespace": "shop", "path": secret_path,
        "skipped": "secret",
    }  # fmt: skip
    assert secret_path not in cluster.reads
    assert cm["existed"] is False and "object" not in cm


async def test_snapshot_skips_huge_objects_and_commands(cluster):
    big = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "cfg"}}
    big["data"] = {"blob": "x" * (executor.SNAPSHOT_MAX_BYTES + 10)}
    cluster.objects[CM_PATH] = big
    plan = ActionPlan(
        kind="apply", title="t", danger="caution",
        ops=[K8sOp("PATCH", CM_PATH, "ConfigMap", "cfg", "shop")],
    )  # fmt: skip
    (entry,) = await executor.snapshot(plan) or []
    assert entry["too_large"] is True and "object" not in entry

    command = ActionPlan(kind="command", title="t", danger="caution", argv=["kubectl", "x"])
    assert await executor.snapshot(command) is None


async def test_record_after_keeps_versions_and_marks_deleted(cluster):
    cluster.objects[DEPLOY_PATH] = deployment(generation=7)
    entries = [
        {"kind": "Deployment", "name": "api", "namespace": "shop", "path": DEPLOY_PATH},
        {"kind": "ConfigMap", "name": "cfg", "namespace": "shop", "path": CM_PATH},
    ]
    await executor.record_after(entries)
    assert entries[0]["after"] == {"resourceVersion": "100", "generation": 7}
    assert entries[1]["after"] is None


# --------------------------------------------------------------------------
# Reverse plans
# --------------------------------------------------------------------------


async def scale_row(cluster, before_replicas: int, after_replicas: int) -> NS:
    cluster.objects[DEPLOY_PATH] = deployment(replicas=before_replicas)
    plan = await planner.plan_scale("deployment", "shop", "api", after_replicas)
    before = await executor.snapshot(plan)
    cluster.objects[DEPLOY_PATH] = deployment(replicas=after_replicas, generation=3)
    await executor.record_after(before or [])
    return executed("scale", plan, before)


async def test_scale_goes_back_to_the_count_before(cluster):
    row = await scale_row(cluster, before_replicas=1, after_replicas=3)
    plan = await revert.plan_revert(row)
    assert plan.title == "Revert: Scale deployment shop/api from 3 to 1 replicas"
    (op,) = plan.ops
    assert (op.method, op.path, op.body) == ("PATCH", DEPLOY_PATH, {"spec": {"replicas": 1}})
    assert plan.verify and plan.verify["type"] == "rollout"
    assert not plan.notes


async def test_scale_says_so_when_it_changed_again_or_is_already_back(cluster):
    row = await scale_row(cluster, before_replicas=1, after_replicas=3)
    cluster.objects[DEPLOY_PATH] = deployment(replicas=5, generation=4)  # someone scaled again
    plan = await revert.plan_revert(row)
    assert "from 5 to 1" in plan.title
    assert any("changed again" in n and "now 5" in n for n in plan.notes)

    cluster.objects[DEPLOY_PATH] = deployment(replicas=1, generation=5)
    with pytest.raises(revert.RevertError, match="already has 1 replica"):
        await revert.plan_revert(row)


async def test_image_goes_back_to_the_previous_image(cluster):
    cluster.objects[DEPLOY_PATH] = deployment(image="acme/api:1.0")
    plan = await planner.plan_set_image("deployment", "shop", "api", "api", "acme/api:2.0")
    before = await executor.snapshot(plan)
    cluster.objects[DEPLOY_PATH] = deployment(image="acme/api:2.0", generation=3)
    row = executed("set_image", plan, before)

    back = await revert.plan_revert(row)
    assert "acme/api:2.0 → acme/api:1.0" in back.title
    (op,) = back.ops
    assert op.body["spec"]["template"]["spec"]["containers"] == [
        {"name": "api", "image": "acme/api:1.0"}
    ]


async def test_apply_deletes_what_it_created_and_restores_what_it_changed(cluster):
    cluster.objects[DEPLOY_PATH] = deployment(replicas=1)
    manifest = """
apiVersion: v1
kind: ConfigMap
metadata: {name: cfg, namespace: shop}
data: {a: b}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: api, namespace: shop}
spec: {replicas: 4}
"""
    plan = await planner.plan_apply(manifest)
    before = await executor.snapshot(plan)
    # The change ran: the ConfigMap exists, the Deployment has 4 replicas.
    cluster.objects[CM_PATH] = {
        "apiVersion": "v1", "kind": "ConfigMap",
        "metadata": {"name": "cfg", "namespace": "shop", "resourceVersion": "5"},
        "data": {"a": "b"},
    }  # fmt: skip
    changed = deployment(replicas=4, generation=3)
    changed["metadata"]["resourceVersion"] = "200"
    cluster.objects[DEPLOY_PATH] = changed
    await executor.record_after(before or [])
    row = executed("apply", plan, before)

    back = await revert.plan_revert(row)
    methods = {(op.method, op.path) for op in back.ops}
    assert methods == {("DELETE", CM_PATH), ("PUT", DEPLOY_PATH)}
    put = next(op for op in back.ops if op.method == "PUT")
    # The earlier version, sent with the CURRENT resourceVersion: a later edit
    # makes the PUT fail (409) instead of being overwritten silently.
    assert put.body["spec"]["replicas"] == 1
    assert put.body["metadata"]["resourceVersion"] == "200"
    assert "status" not in put.body
    assert back.verify == {
        "type": "reverted",
        "exists": [{"path": DEPLOY_PATH, "kind": "Deployment", "name": "api", "namespace": "shop"}],
        "gone": [{"path": CM_PATH, "kind": "ConfigMap", "name": "cfg", "namespace": "shop"}],
    }
    assert back.title.startswith("Revert: Undo #abcd1234: restore 1 object(s) and delete 1")


async def test_apply_with_nothing_left_to_undo_is_refused(cluster):
    cluster.objects[DEPLOY_PATH] = deployment(replicas=1)
    plan = await planner.plan_apply(
        "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: api, namespace: shop}\n"
        "spec: {replicas: 4}\n"
    )
    before = await executor.snapshot(plan)
    row = executed("apply", plan, before)
    # Someone already put it back by hand.
    with pytest.raises(revert.RevertError, match="already as it was before #abcd1234"):
        await revert.plan_revert(row)


async def test_deleted_object_is_recreated_without_owner_or_old_cluster_ip(cluster):
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "web", "namespace": "shop",
            "ownerReferences": [{"kind": "Thing", "name": "x", "uid": "old"}],
        },
        "spec": {"clusterIP": "10.0.0.5", "clusterIPs": ["10.0.0.5"], "ports": [{"port": 80}]},
    }  # fmt: skip
    cluster.objects[SVC_PATH] = service
    plan = await planner.plan_delete("service", "shop", "web")
    before = await executor.snapshot(plan)
    del cluster.objects[SVC_PATH]
    row = executed("delete", plan, before)

    back = await revert.plan_revert(row)
    (op,) = back.ops
    assert (op.method, op.content_type) == ("PATCH", "application/apply-patch+yaml")
    assert "ownerReferences" not in op.body["metadata"]
    assert "clusterIP" not in op.body["spec"] and "clusterIPs" not in op.body["spec"]
    assert op.body["spec"]["ports"] == [{"port": 80}]
    assert back.title == "Revert: Recreate service shop/web deleted by #abcd1234"
    assert any("new cluster IP" in n for n in back.notes)

    cluster.objects[SVC_PATH] = service  # it came back meanwhile
    with pytest.raises(revert.RevertError, match="exists again"):
        await revert.plan_revert(row)


def test_headless_service_stays_headless():
    obj, notes = revert._for_recreate(
        {"kind": "Service", "metadata": {"name": "db"}, "spec": {"clusterIP": "None"}}
    )
    assert obj["spec"]["clusterIP"] == "None" and not notes


# --------------------------------------------------------------------------
# What can't be reverted says why — without asking the cluster
# --------------------------------------------------------------------------


def _row(kind: str, status: str = "executed", before: list | None = None) -> NS:
    row = executed(kind, ActionPlan(kind=kind, title="t", danger="caution"), before)
    row.status = status
    return row


@pytest.mark.parametrize(
    ("row", "match"),
    [
        (_row("scale", status="failed"), "ran successfully"),
        (_row("restart"), "rolling restart"),
        (_row("command"), "command"),
        (_row("mcp"), "external tool"),
        (_row("scale", before=None), "before K8s-Hub recorded"),
        (_row("scale", before=[{"skipped": "secret"}]), "couldn't record"),
        (_row("apply", before=[{"too_large": True}]), "too large"),
        (_row("delete", before=[{"kind": "Namespace", "existed": True, "object": {}}]), "namespace"),
        (
            _row(
                "delete_pod",
                before=[{
                    "kind": "Pod", "existed": True,
                    "object": {"metadata": {"ownerReferences": [{"kind": "ReplicaSet"}]}},
                }],
            ),
            "replacement",
        ),
    ],
)
def test_what_cant_be_reverted_says_why(row, match):
    reason = revert.blocker(row)
    assert reason is not None and match in reason


def test_a_bare_pod_and_a_scale_with_state_are_revertible():
    pod = _row("delete_pod", before=[{"kind": "Pod", "existed": True, "object": {"metadata": {}}}])
    assert revert.blocker(pod) is None


# --------------------------------------------------------------------------
# The proposal: never auto-run, linked back, one at a time
# --------------------------------------------------------------------------


class FakeDb:
    def __init__(self, original: NS, active: NS | None = None) -> None:
        self.original, self.active = original, active

    async def get(self, _model, _id):
        return self.original

    async def execute(self, _stmt):
        return NS(scalar_one_or_none=lambda: self.active)


async def test_a_revert_is_a_pending_proposal_that_points_back(monkeypatch):
    original = _row("scale", before=[{"existed": True, "object": {}}])
    plan = ActionPlan(kind="scale", title="Revert: x", danger="caution")
    seen: dict[str, Any] = {}

    async def fake_plan(row):
        assert row is original
        return plan

    async def fake_propose(p, **kwargs):
        seen.update(kwargs, plan=p)
        return NS(id=uuid.uuid4(), status="pending")

    monkeypatch.setattr(revert, "plan_revert", fake_plan)
    monkeypatch.setattr(approval_service, "propose", fake_propose)
    user = NS(id=uuid.uuid4(), email="eng@example.com", role="admin")
    await approval_service.propose_revert(FakeDb(original), original.id, user)

    assert seen["plan"] is plan
    assert seen["source"] == "revert"
    assert seen["reverts_id"] == original.id
    assert seen["thread_id"] == original.thread_id  # outcome reported in the same chat
    # Built by K8s-Hub, not asked for in words: never auto-run, even for an admin.
    assert seen["actor"].role == "user" and seen["actor"].email == "eng@example.com"


async def test_only_one_revert_waits_at_a_time(monkeypatch):
    original = _row("scale", before=[{"existed": True, "object": {}}])
    user = NS(id=None, email="e@example.com", role="user")
    soon = datetime.now(UTC) + timedelta(minutes=30)
    waiting = NS(id=uuid.uuid4(), status="pending", expires_at=soon)
    with pytest.raises(approval_service.ApprovalError, match="already waiting for approval"):
        await approval_service.propose_revert(FakeDb(original, waiting), original.id, user)

    async def fake_plan(row):
        raise revert.RevertError("Nothing to revert: already back.")

    monkeypatch.setattr(revert, "plan_revert", fake_plan)
    expired = NS(id=uuid.uuid4(), status="pending", expires_at=datetime.now(UTC) - timedelta(1))
    # An expired one doesn't block; the planner's own refusal comes through.
    with pytest.raises(approval_service.ApprovalError, match="already back"):
        await approval_service.propose_revert(FakeDb(original, expired), original.id, user)
