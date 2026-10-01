"""The approval flow's pure parts: plans, diffs, dry-run commands, verification,
the approval event on the stream, the tool budget, and notes back into the chat.

Everything that talks to the cluster is replaced by small fakes: what matters
here is that the plan the approver sees is exactly what would run, and that a
change is never made without one.
"""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from app.integrations.k8s import resources as res
from app.integrations.k8s.diff import object_diff
from app.modules.nl_command import agent, planner
from app.modules.nl_command.dry_run import _command_dry_run_argv
from app.modules.nl_command.planner import ActionPlan
from app.modules.nl_command.verifier import _rollout_state
from app.modules.tools.guard import ToolInputError

# --------------------------------------------------------------------------
# A fake cluster for the planner
# --------------------------------------------------------------------------

DEPLOY = {
    "apiVersion": "apps/v1",
    "kind": "Deployment",
    "metadata": {"name": "api", "namespace": "shop", "generation": 2},
    "spec": {
        "replicas": 1,
        "template": {"spec": {"containers": [{"name": "api", "image": "acme/api:1.0"}]}},
    },
}


@pytest.fixture
def cluster(monkeypatch):
    objects: dict[tuple[str, str | None, str], dict] = {("Deployment", "shop", "api"): DEPLOY}
    hpas: list[dict] = []

    async def get_object(kind, namespace, name):
        return objects.get((kind.kind, namespace, name))

    async def list_objects(kind, namespace, **_):
        return hpas if kind.kind == "HorizontalPodAutoscaler" else []

    monkeypatch.setattr(res, "get_object", get_object)
    monkeypatch.setattr(res, "list_objects", list_objects)
    return NS(objects=objects, hpas=hpas)


async def test_scale_plan_is_an_exact_patch(cluster):
    plan = await planner.plan_scale("deployment", "shop", "api", 3)
    assert plan.title == "Scale deployment shop/api from 1 to 3 replicas"
    (op,) = plan.ops
    assert (op.method, op.path) == ("PATCH", "/apis/apps/v1/namespaces/shop/deployments/api")
    assert op.body == {"spec": {"replicas": 3}}
    assert op.content_type == "application/merge-patch+json"
    assert plan.verify == {"type": "rollout", "kind": "Deployment", "namespace": "shop", "name": "api"}


async def test_scale_to_zero_is_dangerous_and_an_hpa_is_flagged(cluster):
    cluster.hpas.append(
        {
            "metadata": {"name": "api-hpa"},
            "spec": {"scaleTargetRef": {"kind": "Deployment", "name": "api"}},
        }
    )
    plan = await planner.plan_scale("deployment", "shop", "api", 0)
    assert plan.danger == "dangerous"
    assert any("HPA api-hpa" in n for n in plan.notes)


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda: planner.plan_scale("deployment", "shop", "api", 99), "between 0 and 50"),
        (lambda: planner.plan_scale("deployment", "kube-system", "coredns", 2), "protected"),
        (lambda: planner.plan_scale("deployment", "shop", "nope", 2), "does not exist"),
        (lambda: planner.plan_scale("daemonset", "shop", "api", 2), "can't be scaled"),
        (lambda: planner.plan_set_image("deployment", "shop", "api", "web", "x:1"), "no container"),
        (lambda: planner.plan_set_image("deployment", "shop", "api", "api", "bad image"), "Invalid"),
    ],
)
async def test_bad_requests_are_refused_before_any_dry_run(cluster, call, match):
    with pytest.raises(ToolInputError, match=match):
        await call()


async def test_set_image_warns_about_latest(cluster):
    plan = await planner.plan_set_image("deployment", "shop", "api", "api", "acme/api:latest")
    assert "acme/api:1.0 → acme/api:latest" in plan.title
    assert plan.notes and "latest" in plan.notes[0]


async def test_deleting_a_bare_pod_is_dangerous(cluster):
    cluster.objects[("Pod", "shop", "debug")] = {"metadata": {"name": "debug"}}
    cluster.objects[("Pod", "shop", "api-1")] = {
        "metadata": {"name": "api-1", "ownerReferences": [{"kind": "ReplicaSet", "name": "api-7"}]}
    }
    assert (await planner.plan_delete_pod("shop", "debug")).danger == "dangerous"
    owned = await planner.plan_delete_pod("shop", "api-1")
    assert owned.danger == "caution" and "replacement" in owned.notes[0]


async def test_apply_plan_one_server_side_apply_per_object():
    manifest = """
apiVersion: v1
kind: ConfigMap
metadata: {name: cfg}
data: {a: b}
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: {name: reader}
rules: []
"""
    plan = await planner.plan_apply(manifest)
    cm, role = plan.ops
    assert cm.path == "/api/v1/namespaces/default/configmaps/cfg"  # namespace defaulted
    assert cm.body["metadata"]["namespace"] == "default"
    assert cm.content_type == "application/apply-patch+yaml"
    assert ["fieldManager", "k8s-hub"] in cm.query
    assert role.path == "/apis/rbac.authorization.k8s.io/v1/clusterroles/reader"
    assert plan.danger == "dangerous"  # RBAC


@pytest.mark.parametrize(
    ("manifest", "match"),
    [
        ("apiVersion: v1\nkind: Secret\nmetadata: {name: s}\n", "Secrets"),
        ("kind: ConfigMap\nmetadata: {name: c}\n", "apiVersion"),
        ("apiVersion: v1\nkind: ConfigMap\nmetadata: {namespace: kube-system, name: c}\n", "protected"),
        ("a: [", "not valid YAML"),
    ],
)
async def test_apply_refusals(manifest, match):
    with pytest.raises((ToolInputError, res.K8sError), match=match):
        await planner.plan_apply(manifest)


async def test_plans_survive_storage_unchanged(cluster):
    plan = await planner.plan_restart("deployment", "shop", "api")
    again = ActionPlan.from_json(plan.to_json())
    assert again == plan


# --------------------------------------------------------------------------
# Diff, dry-run of commands, verification
# --------------------------------------------------------------------------


def test_diff_shows_only_the_changed_field():
    after = {**DEPLOY, "spec": {**DEPLOY["spec"], "replicas": 3}, "status": {"replicas": 1}}
    text = object_diff(DEPLOY, after, "Deployment shop/api")
    assert "-  replicas: 1" in text and "+  replicas: 3" in text
    assert "status" not in text


def test_diff_of_a_new_object_and_of_no_change():
    assert "+kind: Deployment" in object_diff(None, DEPLOY, "x")
    assert "no change" in object_diff(DEPLOY, DEPLOY, "x")


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["kubectl", "scale", "deploy/api", "--replicas=2"], "--dry-run=server"),
        (["helm", "rollback", "kps", "3"], "--dry-run"),
        (["argocd", "app", "sync", "shop"], None),
        (["kubectl", "exec", "api", "--", "ls"], None),
    ],
)
def test_command_dry_run_only_where_the_cli_has_one(argv, expected):
    got = _command_dry_run_argv(argv)
    assert (got[-1] if got else None) == expected


def test_rollout_state():
    done = {
        "metadata": {"generation": 3},
        "spec": {"replicas": 2},
        "status": {"observedGeneration": 3, "updatedReplicas": 2, "availableReplicas": 2, "replicas": 2},
    }
    assert _rollout_state("Deployment", done)[0]
    rolling = {**done, "status": {**done["status"], "availableReplicas": 1, "replicas": 3}}
    ok, text = _rollout_state("Deployment", rolling)
    assert not ok and "1/2 ready" in text


# --------------------------------------------------------------------------
# The approval event on the stream
# --------------------------------------------------------------------------


async def test_approval_event_is_tied_to_its_tool_call():
    """Through a REAL LangGraph ToolNode: the custom event a tool dispatches
    carries the ToolNode's run id, not the tool call's — an earlier version
    matched on run_id alone, and the approval card vanished after reload."""
    from langchain_core.callbacks import adispatch_custom_event

    from langgraph.graph import END, START, StateGraph
    from langgraph.prebuilt import ToolNode

    from app.integrations.llm.streaming import StreamCollector, stream_graph_events
    from app.modules.nl_command.state import ChatState
    from app.schemas.events import EventStream

    @tool
    async def scale_workload(replicas: int, config: RunnableConfig) -> str:
        """Propose a scale."""
        await adispatch_custom_event(
            "approval_required",
            {"approval_id": "a-1", "summary": "Scale", "diff": "+3", "tool": "scale_workload"},
            config=config,
        )
        return "PROPOSED"

    @tool
    async def ping() -> str:
        """Pong."""
        return "pong"

    async def assistant(state):  # noqa: ARG001
        return {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "ping", "args": {}, "id": "c0"},
                        {"name": "scale_workload", "args": {"replicas": 3}, "id": "c1"},
                    ],
                )
            ]
        }

    g = StateGraph(ChatState)
    g.add_node("assistant", assistant)
    g.add_node("tools", ToolNode([ping, scale_workload]))
    g.add_edge(START, "assistant")
    g.add_edge("assistant", "tools")
    g.add_edge("tools", END)

    collector = StreamCollector()
    frames = [
        f
        async for f in stream_graph_events(
            g.compile(), {"messages": [HumanMessage("x")]}, stream=EventStream(), collector=collector
        )
    ]
    approval = next(f for f in frames if f["event"] == "approval_required")
    calls = {tc["name"]: tc for tc in collector.tool_calls_as_dicts()}
    assert calls["scale_workload"]["approval_id"] == "a-1"
    assert calls["ping"]["approval_id"] is None
    assert f'"tool_call_id":"{calls["scale_workload"]["call_id"]}"' in approval["data"]


def test_model_is_told_nothing_happened_yet():
    from app.services.approval_service import message_for_model

    row = NS(
        id="12345678-aaaa", status="pending", kind="scale", title="Scale x", diff="+a",
        dry_run_output=None,
    )
    text = message_for_model(row)
    assert text.startswith("PROPOSED, NOT DONE") and "do NOT say it has been done" in text


# --------------------------------------------------------------------------
# Tool budget (item: no more "too many tool calls" errors)
# --------------------------------------------------------------------------


@tool
def ping() -> str:
    """Answer pong."""
    return "pong"


class LoopingModel:
    """Asks for a tool forever when tools are bound; answers when they aren't."""

    def __init__(self) -> None:
        self.forced: list[list] = []
        self.rounds = 0

    def bind_tools(self, _tools):
        outer = self

        class Bound:
            async def ainvoke(self, messages, config=None):  # noqa: ARG002
                outer.rounds += 1
                return AIMessage(
                    content="", tool_calls=[{"name": "ping", "args": {}, "id": f"c{outer.rounds}"}]
                )

        return Bound()

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        self.forced.append(list(messages))
        return AIMessage(content="final answer with what I found")


async def test_tool_budget_ends_in_an_answer_not_an_error(monkeypatch):
    model = LoopingModel()
    monkeypatch.setattr(agent, "get_llm", lambda **_: model)
    graph = agent.build_chat_graph(tools=[ping])
    out = await graph.ainvoke(
        {"messages": [HumanMessage("dig forever")]},
        config={"recursion_limit": agent.RECURSION_LIMIT},
    )
    assert out["messages"][-1].content == "final answer with what I found"
    assert model.rounds == agent.MAX_TOOL_ROUNDS
    last = model.forced[0][-1]
    assert isinstance(last, SystemMessage) and "Do NOT call any tool" in last.content


# --------------------------------------------------------------------------
# Decisions reported back into the conversation
# --------------------------------------------------------------------------


def test_system_notes_ride_on_the_next_user_message():
    rows = [
        NS(role="user", content="scale api to 3", status="complete"),
        NS(role="assistant", content="Proposed, waiting for approval.", status="complete"),
        NS(role="system", content='The proposed change "Scale" was approved…', status="complete"),
        NS(role="user", content="is it done?", status="complete"),
    ]
    messages = agent.history_to_messages(rows)
    assert [type(m).__name__ for m in messages] == ["HumanMessage", "AIMessage", "HumanMessage"]
    assert messages[-1].content.startswith("[K8s-Hub update")
    assert "was approved" in messages[-1].content and messages[-1].content.endswith("is it done?")


# --------------------------------------------------------------------------
# "Sending the proposal…" without calling the tool (seen on lab1 with gpt-oss)
# --------------------------------------------------------------------------

NARRATED = (
    "Manifest:\n```yaml\napiVersion: v1\nkind: Pod\nmetadata:\n  name: nginx\n```\n"
    "Đang gửi đề xuất tới hệ thống để chờ phê duyệt…"
)


class NarratingModel:
    """Narrates first; calls apply_manifest once told; then confirms."""

    def __init__(self) -> None:
        self.calls: list[list] = []

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        self.calls.append(list(messages))
        n = len(self.calls)
        if n == 1:
            return AIMessage(content=NARRATED)
        if n == 2:
            return AIMessage(
                content="",
                tool_calls=[{"name": "apply_manifest", "args": {"manifest": "x"}, "id": "c1"}],
            )
        return AIMessage(content="Proposed; waiting for an engineer's approval.")


@tool
async def apply_manifest(manifest: str) -> str:
    """Fake write tool (same name as the real one, so it counts as a write tool)."""
    return "PROPOSED, NOT DONE."


async def test_narrated_change_gets_one_nudge_to_call_the_tool(monkeypatch):
    model = NarratingModel()
    monkeypatch.setattr(agent, "get_llm", lambda **_: model)
    graph = agent.build_chat_graph(tools=[apply_manifest])
    out = await graph.ainvoke({"messages": [HumanMessage("tạo pod nginx")]})
    assert len(model.calls) == 3
    nudge = model.calls[1][-1]
    assert isinstance(nudge, SystemMessage) and "did not call any write tool" in nudge.content
    assert any(
        isinstance(m, AIMessage) and m.tool_calls and m.tool_calls[0]["name"] == "apply_manifest"
        for m in out["messages"]
    )


async def test_no_nudge_after_a_real_proposal_or_for_plain_answers(monkeypatch):
    class Plain:
        def __init__(self, text):
            self.text, self.calls = text, 0

        def bind_tools(self, _t):
            return self

        async def ainvoke(self, messages, config=None):  # noqa: ARG002
            self.calls += 1
            return AIMessage(content=self.text)

    for text in ("kube-system looks healthy.", "The proposal is waiting for approval."):
        model = Plain(text)
        monkeypatch.setattr(agent, "get_llm", lambda **_: model)  # noqa: B023
        await agent.build_chat_graph(tools=[apply_manifest]).ainvoke(
            {"messages": [HumanMessage("x")]}
        )
        assert model.calls == 1, text


# --------------------------------------------------------------------------
# A namespace and objects inside it, in one change
# --------------------------------------------------------------------------

NS_AND_POD = """
apiVersion: v1
kind: Pod
metadata: {name: nginx, namespace: nginx}
spec:
  containers: [{name: nginx, image: nginx}]
---
apiVersion: v1
kind: Namespace
metadata: {name: nginx}
"""


async def test_namespace_is_created_first_and_floating_tags_are_flagged():
    plan = await planner.plan_apply(NS_AND_POD)
    assert [op.kind for op in plan.ops] == ["Namespace", "Pod"]
    assert any("nginx" in n and "no fixed tag" in n for n in plan.notes)


async def test_objects_in_a_new_namespace_are_not_server_dry_run(monkeypatch):
    from app.modules.nl_command import dry_run as dr

    seen: list[tuple[str, str]] = []

    async def fake_request(method, path, *, query=None, body=None, content_type=None):  # noqa: ARG001
        seen.append((method, path))
        if method == "GET":
            return 404, {}
        return 200, body

    monkeypatch.setattr(res, "request", fake_request)
    result = await dr.dry_run(await planner.plan_apply(NS_AND_POD))
    assert result.ok
    assert ("PATCH", "/api/v1/namespaces/nginx/pods/nginx") not in seen
    assert "can't be dry-run before its namespace exists" in result.output
    assert "+kind: Pod" in result.diff


async def test_asking_the_user_for_details_is_not_nudged(monkeypatch):
    """Qwen on lab1 asked "which tag? limits? expose?" — the right move — and an
    earlier, broader pattern nudged it anyway ("sẽ tạo" matched)."""

    class Asks:
        calls = 0

        def bind_tools(self, _t):
            return self

        async def ainvoke(self, messages, config=None):  # noqa: ARG002
            Asks.calls += 1
            return AIMessage(
                content=(
                    "Namespace `nginx` chưa tồn tại, nên mình sẽ tạo cả namespace lẫn pod. "
                    "Image dùng tag nào? Có cần set resource limits không?"
                )
            )

    monkeypatch.setattr(agent, "get_llm", lambda **_: Asks())
    await agent.build_chat_graph(tools=[apply_manifest]).ainvoke({"messages": [HumanMessage("x")]})
    assert Asks.calls == 1


# --------------------------------------------------------------------------
# delete_resource — before it existed, "delete the namespace" became an
# apply_manifest of that namespace: approved, "executed", and nothing deleted.
# --------------------------------------------------------------------------


async def test_delete_one_object_of_any_kind(cluster):
    plan = await planner.plan_delete("deploy", "shop", "api")
    (op,) = plan.ops
    assert (op.method, op.path) == ("DELETE", "/apis/apps/v1/namespaces/shop/deployments/api")
    assert plan.danger == "dangerous"
    assert plan.verify == {"type": "deleted", "kind": "Deployment", "namespace": "shop", "name": "api"}


async def test_deleting_a_namespace_warns_it_takes_everything(cluster):
    cluster.objects[("Namespace", None, "nginx")] = {"metadata": {"name": "nginx"}}
    plan = await planner.plan_delete("namespace", "", "nginx")
    assert plan.ops[0].path == "/api/v1/namespaces/nginx"
    assert "EVERYTHING" in plan.notes[0]


@pytest.mark.parametrize(
    ("kind", "ns", "name", "match"),
    [
        ("namespace", "", "kube-system", "protected"),
        ("namespace", "", "default", "built in"),
        ("node", "", "lab1", "whole cluster"),
        ("secret", "shop", "db", "Secrets"),
        ("deploy", "shop", "nope", "does not exist"),
    ],
)
async def test_delete_refusals(cluster, kind, ns, name, match):
    with pytest.raises((ToolInputError, res.K8sError), match=match):
        await planner.plan_delete(kind, ns, name)


async def test_long_listings_are_cut_for_the_model(monkeypatch):
    from app.modules.tools.builtin import resources as rt

    pods = [
        {"metadata": {"name": f"pod-{i:03d}-" + "x" * 40, "namespace": "shop"}, "status": {}}
        for i in range(100)
    ]

    async def list_objects(kind, namespace, **_):
        return pods

    monkeypatch.setattr(res, "list_objects", list_objects)
    out = await rt.get_resources.ainvoke({"kind": "pod"})
    assert len(out) < rt.MAX_LIST_CHARS + 300
    assert "output cut after" in out
