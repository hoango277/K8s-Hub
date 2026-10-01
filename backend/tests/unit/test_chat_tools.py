"""Tests for the tools the assistant is allowed to call.

Before this file existed, no test ACTUALLY called a tool — they were only
checked indirectly through fake event streams. The consequence: a change that
made `system_info` misread its `config` parameter (a RunnableConfig, not
Settings) still passed the whole test suite, and only blew up when a user
actually asked.
"""

from __future__ import annotations

import pytest

from app.modules.nl_command.tools import CORE_TOOLS, current_time, get_tools, system_info
from app.modules.skills.agent_tools import load_skill, read_skill_file, run_skill_script
from app.modules.tools.registry import BUILTIN

# Every tool the agent can ever get: core, the three skill tools, built-in cluster tools.
ALL_TOOLS = [*CORE_TOOLS, load_skill, read_skill_file, run_skill_script, *(s.tool for s in BUILTIN)]


def call(tool, metadata: dict | None = None) -> str:
    """Call the tool the same way LangGraph calls it."""
    return tool.invoke({}, config={"metadata": metadata or {}})


# --------------------------------------------------------------------------
# Actually runs
# --------------------------------------------------------------------------


# Tools with required arguments get a sample value.
SAMPLE_ARGS: dict[str, dict] = {
    "get_trace": {"trace_id": "0af7651916cd43dd8448eb211c80319c"},
    "load_skill": {"name": "diagnose-crashloop"},
    "read_skill_file": {"name": "diagnose-crashloop", "path": "references/exit-codes.md"},
    "run_skill_script": {"name": "no-such-skill", "script": "scripts/x.py"},
    "list_pods": {"namespace": "default"},
    "describe_pod": {"namespace": "default", "name": "web-1"},
    "get_pod_logs": {"namespace": "default", "name": "web-1"},
    "list_events": {"namespace": "default"},
    "list_deployments": {"namespace": "default"},
    "pod_metrics": {"namespace": "default", "pod": "web", "metric": "cpu"},
    "search_logs": {"namespace": "default"},
    "get_resources": {"kind": "service"},
    "describe_resource": {"kind": "service", "name": "web", "namespace": "default"},
    "scale_workload": {"kind": "deployment", "namespace": "default", "name": "web", "replicas": 2},
    "restart_workload": {"kind": "deployment", "namespace": "default", "name": "web"},
    "set_image": {
        "kind": "deployment", "namespace": "default", "name": "web",
        "container": "web", "image": "nginx:1.27",
    },
    "delete_pod": {"namespace": "default", "name": "web-1"},
    "delete_resource": {"kind": "configmap", "name": "web", "namespace": "default"},
    "apply_manifest": {
        "manifest": "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: demo\ndata: {a: b}\n"
    },
}


@pytest.fixture
def offline(monkeypatch):
    """Unit tests never reach the network: every data source is 'not configured'."""
    from app.core.config import Settings
    from app.integrations.k8s import client as k8s
    from app.integrations.loki import client as loki
    from app.integrations.prometheus import client as prom
    from app.integrations.tempo import client as tempo

    empty = Settings(_env_file=None, TEMPO_URL="", PROMETHEUS_URL="", LOKI_URL="")
    for module in (tempo, prom, loki):
        monkeypatch.setattr(module, "get_settings", lambda: empty)
    # No pod, no kubeconfig: the Kubernetes tools must see no credentials.
    monkeypatch.delenv("KUBERNETES_SERVICE_HOST", raising=False)
    monkeypatch.setattr(k8s, "_kubeconfig_files", lambda: [])
    assert k8s.config_problem() is not None


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
async def test_every_tool_runs(tool, offline):
    """Really call each tool, sync or async, the way LangGraph does. Catches
    'misread attribute' bugs right here."""
    args = SAMPLE_ARGS.get(tool.name, {})
    config = {"metadata": {}}
    if tool.coroutine is not None:
        result = await tool.ainvoke(args, config=config)
    else:
        result = tool.invoke(args, config=config)

    assert isinstance(result, str)
    assert result.strip()


def test_no_error_without_metadata():
    """LangGraph may call the tool without any metadata."""
    assert system_info.invoke({}).strip()


# --------------------------------------------------------------------------
# system_info must report the model that is ACTUALLY running
# --------------------------------------------------------------------------


def test_reports_the_model_of_this_turn():
    """When the user picks a model for a single turn, the tool must report it.

    Reading the global configuration would make the assistant misreport itself
    right after the user switched models in the UI.
    """
    result = call(
        system_info,
        {"llm_provider": "google", "llm_model": "gemini-2.5-flash"},
    )

    assert "google / gemini-2.5-flash" in result


def test_falls_back_to_global_config_without_selection():
    from app.core.config import get_settings

    cfg = get_settings()
    result = call(system_info)

    assert f"{cfg.llm_default_provider()} / {cfg.llm_model_name()}" in result


def test_includes_operational_info():
    """This tool exists to answer 'which mode is the system in'."""
    result = call(system_info)

    for part in ("AI model:", "Execution mode:", "Allowed namespaces:"):
        assert part in result


# --------------------------------------------------------------------------
# The `config` parameter must not be exposed to the model
# --------------------------------------------------------------------------


def test_model_does_not_see_config_parameter():
    """`config` is injected by LangChain, not something the model fills in.

    If it leaked into the schema, the model would try to generate a
    RunnableConfig object — wasting tokens and inviting bad calls.
    """
    fields = system_info.args_schema.model_json_schema().get("properties", {})

    assert "config" not in fields


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.name)
def test_has_description_for_the_model(tool):
    """The description is what the model relies on to decide whether to call."""
    assert (tool.description or "").strip()


# --------------------------------------------------------------------------
# Safety boundaries
# --------------------------------------------------------------------------


def test_no_tool_accepts_raw_command_strings():
    """There must be no tool like `run_kubectl(cmd)`.

    Parameters must be discrete fields so they can be checked before running.
    Accepting raw command strings opens the door to the model inventing
    arbitrary commands.
    """
    forbidden = {"cmd", "command", "shell", "script", "kubectl", "query_raw", "promql", "logql"}
    # run_skill_script takes `script`, but it is the PATH of a file an engineer
    # wrote into the skill's scripts/ folder — not a command. Scripts run on the
    # backend by decision (see app/modules/skills/scripts.py); what can run is
    # whatever engineers put in skills, never text the model makes up.
    exempt = {"run_skill_script"}

    for tool in ALL_TOOLS:
        if tool.name in exempt:
            continue
        fields = set(tool.tool_call_schema.model_json_schema().get("properties", {}))
        assert not (fields & forbidden), f"{tool.name} accepts dangerous parameters: {fields}"


async def test_run_skill_script_refuses_files_outside_scripts():
    text = await run_skill_script.ainvoke(
        {"name": "diagnose-crashloop", "script": "references/exit-codes.md"},
        config={"metadata": {}},
    )
    assert "Only files inside scripts/ can be run" in text


def test_get_tools_returns_a_copy():
    """Callers adding/removing tools must not corrupt the original list."""
    tools = get_tools()
    tools.clear()

    assert len(get_tools()) > 0


def test_current_time_returns_utc():
    assert "UTC" in call(current_time)
