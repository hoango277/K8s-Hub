"""External MCP tools: the client (in-process server, no network) and the
per-tool policy engineers set — enabled, and whether each call needs approval."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from app.modules.nl_command.dry_run import dry_run
from app.modules.nl_command.planner import plan_mcp
from app.modules.tools import mcp_client
from app.modules.tools.mcp import McpToolRecord, mcp_tool_name
from app.modules.tools.registry import ToolRegistry
from app.modules.tools.schema import Category, Danger


@pytest.fixture
def server() -> MCPServer:
    srv = MCPServer("demo")

    @srv.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @srv.tool()
    def fail() -> str:
        """Always fails."""
        raise RuntimeError("nope")

    return srv


async def test_list_and_call_tools_of_an_mcp_server(server):
    tools = await mcp_client.list_tools("mem://demo", _server=server)
    assert {t.name for t in tools} == {"add", "fail"}
    add = next(t for t in tools if t.name == "add")
    assert add.input_schema["required"] == ["a", "b"]
    assert await mcp_client.call_tool("mem://demo", "add", {"a": 2, "b": 3}, _server=server) == "5"


async def test_tool_error_becomes_a_readable_message(server):
    with pytest.raises(mcp_client.McpError, match="reported an error"):
        await mcp_client.call_tool("mem://demo", "fail", {}, _server=server)


def test_tool_names_are_legal_for_model_providers():
    assert mcp_tool_name("my server", "get.thing/v2") == "my_server__get_thing_v2"


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------


def _record(**kw) -> McpToolRecord:
    base = dict(
        server_id="00000000-0000-0000-0000-000000000001",
        server_name="demo",
        server_url="http://demo/mcp",
        tool="add",
        description="Add two numbers.",
        input_schema={
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
            "required": ["a", "b"],
        },
        read_only_hint=True,
    )
    base.update(kw)
    return McpToolRecord(**base)


def test_new_tools_start_disabled_and_needing_approval_whatever_the_server_claims():
    rec = _record()  # the server says read-only
    assert rec.enabled is False and rec.requires_approval is True
    reg = ToolRegistry()
    reg.set_mcp_tools("demo", [rec])
    spec = reg.get("demo__add")
    assert spec.category is Category.MCP and spec.source == "mcp:demo"
    assert spec.danger is Danger.WRITE
    assert reg.can_run(spec) == "This tool is disabled."
    assert all(t.name != "demo__add" for t in reg.chat_tools())


def test_engineer_policy_changes_what_the_catalog_and_the_model_see():
    reg = ToolRegistry()
    reg.set_mcp_tools("demo", [_record()])
    reg.set_mcp_policy("demo__add", enabled=True, requires_approval=False)
    spec = reg.get("demo__add")
    assert spec.danger is Danger.READ
    assert "Runs directly" in spec.description
    assert any(t.name == "demo__add" for t in reg.chat_tools())
    reg.set_mcp_policy("demo__add", requires_approval=True)
    assert "waits for an engineer's approval" in reg.get("demo__add").description


@pytest.fixture
def live_registry(monkeypatch):
    """Point the module-level registry the tool reads at call time to a fresh one."""
    from app.modules.tools import registry as registry_module

    reg = ToolRegistry()
    monkeypatch.setattr(registry_module, "registry", reg)
    return reg


async def test_a_tool_needing_approval_proposes_instead_of_calling(live_registry, monkeypatch):
    from app.modules.tools.builtin import actions

    async def must_not_call(*a, **kw):
        raise AssertionError("the server must not be called before approval")

    proposed = {}

    async def fake_propose(build, *, source, config):
        proposed["plan"] = await build()
        proposed["source"] = source
        return "PROPOSED"

    monkeypatch.setattr(mcp_client, "call_tool", must_not_call)
    monkeypatch.setattr(actions, "propose", fake_propose)
    live_registry.set_mcp_tools("demo", [_record(enabled=True, requires_approval=True)])

    out = await live_registry.get("demo__add").tool.ainvoke({"a": 2, "b": 3})
    assert out == "PROPOSED"
    plan = proposed["plan"]
    assert plan.kind == "mcp" and proposed["source"] == "demo__add"
    assert plan.mcp == {
        "server_id": "00000000-0000-0000-0000-000000000001",
        "server": "demo",
        "url": "http://demo/mcp",
        "tool": "add",
        "args": {"a": 2, "b": 3},
    }


async def test_a_tool_without_approval_is_called_directly(live_registry, monkeypatch):
    from app.services import tool_service

    calls = []

    async def fake_call(url, tool, args, token=None):
        calls.append((url, tool, args, token))
        return "5"

    async def fake_token(server_id):
        return "secret-token"

    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    monkeypatch.setattr(tool_service, "server_token", fake_token)
    live_registry.set_mcp_tools("demo", [_record(enabled=True, requires_approval=False)])

    assert await live_registry.get("demo__add").tool.ainvoke({"a": 2, "b": 3}) == "5"
    assert calls == [("http://demo/mcp", "add", {"a": 2, "b": 3}, "secret-token")]


async def test_policy_is_read_at_call_time(live_registry, monkeypatch):
    """A tool switched back to "needs approval" must not run directly on its next
    call, even if the spec was handed to a chat turn before the change."""
    from app.modules.tools.builtin import actions

    async def fake_propose(build, *, source, config):
        return "PROPOSED"

    monkeypatch.setattr(actions, "propose", fake_propose)
    live_registry.set_mcp_tools("demo", [_record(enabled=True, requires_approval=False)])
    tool_given_to_the_model = live_registry.get("demo__add").tool
    live_registry.set_mcp_policy("demo__add", requires_approval=True)
    assert await tool_given_to_the_model.ainvoke({"a": 1, "b": 1}) == "PROPOSED"


async def test_an_approved_call_shows_the_exact_arguments_and_runs():
    plan = plan_mcp(
        server_id="x", server="demo", url="http://demo/mcp", tool="add", args={"a": 2, "b": 3}
    )
    result = await dry_run(plan)
    assert result.ok
    assert '+  "a": 2,' in result.diff and "no dry-run" in result.output


async def test_executor_calls_the_server_with_its_current_token(monkeypatch):
    from app.modules.nl_command import executor
    from app.services import tool_service

    async def fake_token(server_id):
        return "t"

    async def fake_call(url, tool, args, token=None):
        assert (url, tool, args, token) == ("http://demo/mcp", "add", {"a": 2, "b": 3}, "t")
        return "5"

    monkeypatch.setattr(tool_service, "server_token", fake_token)
    monkeypatch.setattr(mcp_client, "call_tool", fake_call)
    plan = plan_mcp(
        server_id="x", server="demo", url="http://demo/mcp", tool="add", args={"a": 2, "b": 3}
    )
    assert await executor.execute(plan) == (True, "5")


def test_model_is_not_told_an_mcp_call_was_dry_run():
    from types import SimpleNamespace as NS

    from app.services.approval_service import message_for_model

    row = NS(
        id="12345678", status="pending", kind="mcp", title="Call x", diff="+{}",
        dry_run_output=None, risk_flags=None,
    )
    text = message_for_model(row)
    assert "dry-run" in text and "passed the server dry-run" not in text
