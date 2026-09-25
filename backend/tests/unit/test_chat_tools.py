"""Tests for the tools the assistant is allowed to call.

Before this file existed, no test ACTUALLY called a tool — they were only
checked indirectly through fake event streams. The consequence: a change that
made `system_info` misread its `config` parameter (a RunnableConfig, not
Settings) still passed the whole test suite, and only blew up when a user
actually asked.
"""

from __future__ import annotations

import pytest

from app.modules.nl_command.tools import CHAT_TOOLS, current_time, get_tools, system_info


def call(tool, metadata: dict | None = None) -> str:
    """Call the tool the same way LangGraph calls it."""
    return tool.invoke({}, config={"metadata": metadata or {}})


# --------------------------------------------------------------------------
# Actually runs
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tool", CHAT_TOOLS, ids=lambda t: t.name)
def test_every_tool_runs(tool):
    """Really call each tool. Catches 'misread attribute' bugs right here."""
    result = call(tool)

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


@pytest.mark.parametrize("tool", CHAT_TOOLS, ids=lambda t: t.name)
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
    forbidden = {"cmd", "command", "shell", "script", "kubectl", "query_raw"}

    for tool in CHAT_TOOLS:
        fields = set(tool.args_schema.model_json_schema().get("properties", {}))
        assert not (fields & forbidden), f"{tool.name} accepts dangerous parameters: {fields}"


def test_get_tools_returns_a_copy():
    """Callers adding/removing tools must not corrupt the original list."""
    tools = get_tools()
    tools.clear()

    assert len(get_tools()) == len(CHAT_TOOLS) > 0


def test_current_time_returns_utc():
    assert "UTC" in call(current_time)
