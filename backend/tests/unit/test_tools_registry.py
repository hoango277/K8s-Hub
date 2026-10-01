"""Tool registry, custom CLI tools (kubectl-ai style), and built-in tool helpers."""

from __future__ import annotations

import pytest

from app.modules.nl_command import intent
from app.modules.tools.builtin.logs import build_logql
from app.modules.tools.custom import CustomToolDef
from app.modules.tools.guard import ToolInputError
from app.modules.tools.registry import ToolRegistry
from app.modules.tools.schema import Danger


def _kubectl(**kw) -> CustomToolDef:
    return CustomToolDef(
        name="kubectl",
        title="kubectl",
        description="The Kubernetes CLI.",
        command="kubectl",
        read_only_prefixes=["get", "describe", "rollout status"],
        **kw,
    )


def test_custom_tools_are_listed_and_toggled_on_their_own_row():
    reg = ToolRegistry()
    reg.set_custom_tools([_kubectl()])
    spec = reg.get("kubectl")
    assert spec is not None and spec.source == "custom"
    assert spec.danger is Danger.WRITE  # mixed read/change: never shown as harmless
    assert reg.is_enabled(spec)
    reg.set_enabled("kubectl", False)
    assert reg.can_run(spec) == "This tool is disabled."
    assert reg.custom_def("kubectl").enabled is False


def test_removing_a_custom_tool_takes_it_out_of_the_chat():
    reg = ToolRegistry()
    reg.set_custom_tools([_kubectl()])
    reg.remove_custom("kubectl")
    assert reg.get("kubectl") is None
    assert all(t.name != "kubectl" for t in reg.chat_tools())


def test_builtin_tools_can_be_switched_off():
    reg = ToolRegistry()
    reg.set_enabled("list_pods", False)
    assert reg.can_run(reg.get("list_pods")) == "This tool is disabled."


def test_write_tools_are_not_offered_in_read_only_mode(monkeypatch):
    from app.core.config import Settings
    from app.modules.tools.builtin import actions

    monkeypatch.setattr(
        actions, "get_settings", lambda: Settings(_env_file=None, K8S_EXECUTION_MODE="read_only")
    )
    reg = ToolRegistry()
    assert "read_only" in (reg.can_run(reg.get("scale_workload")) or "")


# --- read or change? (intent.py) -------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ("get pods -n shop", "read"),
        ("kubectl get pods -n shop", "read"),  # the program repeated: dropped
        ("rollout status deployment/api -n shop", "read"),
        ("rollout restart deployment/api -n shop", "write"),
        ("delete pod x -n shop", "write"),
        ("getx pods", "write"),  # a prefix matches whole words only
    ],
)
def test_classify_by_read_only_prefixes(args, expected):
    tokens = intent.split_arguments("kubectl", args)
    assert intent.classify(tokens, ["get", "describe", "rollout status"]) == expected


def test_shell_syntax_is_just_arguments():
    # No shell: "; rm -rf /" can't become a second command.
    tokens = intent.split_arguments("kubectl", "get pods; rm -rf /")
    assert tokens == ["get", "pods;", "rm", "-rf", "/"]
    assert intent.classify(tokens, ["get"]) == "read"


@pytest.mark.parametrize(
    "args",
    [
        "get secrets -n shop",
        "get secret/db -n shop",
        "logs api -f -n shop",
        "get pods -w",
        "exec -it api -n shop -- sh",
        "port-forward svc/api 8080:80",
    ],
)
def test_refused_arguments(args):
    tokens = intent.split_arguments("kubectl", args)
    with pytest.raises(ToolInputError):
        intent.check_tokens(tokens)


def test_helm_install_flag_is_not_mistaken_for_a_tty():
    intent.check_tokens(intent.split_arguments("helm", "upgrade -i kps chart -n monitoring"))


@pytest.mark.parametrize(
    ("args", "ns"),
    [("get pods -n shop", "shop"), ("get pods --namespace=shop", "shop"), ("get pods", None)],
)
def test_namespace_of(args, ns):
    assert intent.namespace_of(intent.split_arguments("kubectl", args)) == ns


async def test_custom_tool_read_runs_in_the_sandbox(monkeypatch):
    from app.modules.sandbox.base import ExecResult
    from app.modules.tools import custom

    seen = {}

    async def fake_run(argv, *, time_limit):
        seen["argv"] = argv
        return ExecResult(exit_code=0, stdout="pod-a Running", stderr="", duration_ms=5)

    monkeypatch.setattr(custom, "run_command", fake_run)
    spec = custom.build_spec(_kubectl())
    out = await spec.tool.ainvoke({"arguments": "get pods -n shop"})
    assert seen["argv"] == ["kubectl", "get", "pods", "-n", "shop"]
    assert "pod-a Running" in out and "exit 0" in out


async def test_custom_tool_change_is_proposed_not_run(monkeypatch):
    from app.modules.tools import custom
    from app.modules.tools.builtin import actions

    async def must_not_run(*a, **kw):
        raise AssertionError("a change must not run before approval")

    proposed = {}

    async def fake_propose(build, *, source, config):
        plan = await build()
        proposed["plan"] = plan
        return "PROPOSED"

    monkeypatch.setattr(custom, "run_command", must_not_run)
    monkeypatch.setattr(actions, "propose", fake_propose)
    spec = custom.build_spec(_kubectl())
    out = await spec.tool.ainvoke({"arguments": "delete pod api-1 -n shop"})
    assert out == "PROPOSED"
    plan = proposed["plan"]
    assert plan.argv == ["kubectl", "delete", "pod", "api-1", "-n", "shop"]
    assert plan.danger == "dangerous" and plan.namespace == "shop"


async def test_custom_tool_refuses_changes_in_protected_namespaces():
    from app.modules.tools import custom

    spec = custom.build_spec(_kubectl())
    out = await spec.tool.ainvoke({"arguments": "delete pod coredns-1 -n kube-system"})
    assert "protected" in out


def test_logql_text_filter_is_an_escaped_literal():
    q = build_logql(namespace="shop", pod="web", app=None, contains='a"b\\c', errors_only=False)
    assert q == '{namespace="shop", pod=~"web.*"} |= "a\\"b\\\\c"'


@pytest.mark.parametrize("pod", ['web"} or {x="', "a.b", "Web"])
def test_logql_rejects_unsafe_pod_prefixes(pod):
    with pytest.raises(ToolInputError):
        build_logql(namespace="shop", pod=pod, app=None, contains=None, errors_only=False)


# --------------------------------------------------------------------------
# list_pods groups pods by their CURRENT state
# --------------------------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402

from app.modules.tools.builtin import kubernetes as k8s_tools  # noqa: E402


def _pod(phase, *, ready=True, restarts=0, waiting=None, last=None):
    ago = datetime.now(UTC) - timedelta(hours=20)
    status = NS(
        name="app", ready=ready, restart_count=restarts,
        state=NS(waiting=NS(reason=waiting, message="") if waiting else None, terminated=None, running=None),
        last_state=NS(terminated=NS(reason=last[0], exit_code=last[1], finished_at=ago)) if last else None,
    )
    return NS(
        metadata=NS(name=f"p-{phase}-{waiting}-{restarts}", creation_timestamp=ago),
        status=NS(phase=phase, container_statuses=[status]),
        spec=NS(node_name="lab1"),
    )


def test_running_pod_with_old_restarts_is_not_failing():
    group, row = k8s_tools._pod_row(_pod("Running", restarts=16, last=("Error", 143)))
    assert group == k8s_tools.RESTARTED
    assert "16 restart(s), last one 20h ago (Error, exit 143)" in row


def test_crashloop_is_failing_now():
    group, row = k8s_tools._pod_row(
        _pod("Running", ready=False, restarts=5, waiting="CrashLoopBackOff", last=("OOMKilled", 137))
    )
    assert group == k8s_tools.FAILING and "CrashLoopBackOff (last exit OOMKilled, code 137)" in row


def test_finished_probe_pod_is_completed_not_a_problem():
    group, _ = k8s_tools._pod_row(_pod("Succeeded", ready=False))
    assert group == k8s_tools.COMPLETED
