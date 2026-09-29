"""Tests for the tool registry and MCP tools, with an in-process MCP server (no network)."""

from __future__ import annotations

import pytest
from mcp.server.mcpserver import MCPServer

from app.modules.tools import mcp_client
from app.modules.tools.builtin.logs import build_logql
from app.modules.tools.guard import ToolInputError
from app.modules.tools.registry import McpToolRecord, ToolRegistry, mcp_tool_name
from app.modules.tools.schema import Danger


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


def _record(tool="add"):
    return McpToolRecord(
        server_name="demo", server_url="http://x/mcp", token=None, tool=tool,
        description="Add two numbers.", input_schema={"type": "object", "properties": {}},
        read_only_hint=True,
    )


def test_external_tools_start_disabled_and_write_whatever_the_server_claims():
    reg = ToolRegistry()
    reg.set_mcp_tools("demo", [_record()])
    spec = reg.get("demo__add")
    assert spec is not None
    assert not reg.is_enabled(spec)
    assert reg.danger(spec) is Danger.WRITE  # readOnlyHint=True is NOT trusted
    assert spec.tool not in reg.chat_tools()


def test_reviewed_external_tool_reaches_the_chat():
    reg = ToolRegistry()
    reg.set_mcp_tools("demo", [_record()])
    reg.set_state("demo__add", enabled=True)
    assert reg.can_run(reg.get("demo__add")) is not None  # still WRITE
    reg.set_state("demo__add", danger=Danger.READ)
    assert reg.can_run(reg.get("demo__add")) is None


def test_builtin_danger_cannot_be_downgraded():
    reg = ToolRegistry()
    reg.set_state("list_pods", danger=Danger.DESTRUCTIVE)
    assert reg.danger(reg.get("list_pods")) is Danger.READ


def test_removing_a_server_removes_its_tools():
    reg = ToolRegistry()
    reg.set_mcp_tools("demo", [_record("add"), _record("sub")])
    reg.remove_mcp_server("demo")
    assert reg.get("demo__add") is None and reg.get("demo__sub") is None


def test_tool_names_are_legal_for_model_providers():
    assert mcp_tool_name("my server", "get.thing/v2") == "my_server__get_thing_v2"


def test_logql_text_filter_is_an_escaped_literal():
    q = build_logql(namespace="shop", pod="web", app=None, contains='a"b\\c', errors_only=False)
    assert q == '{namespace="shop", pod=~"web.*"} |= "a\\"b\\\\c"'


@pytest.mark.parametrize("pod", ['web"} or {x="', "a.b", "Web"])
def test_logql_rejects_unsafe_pod_prefixes(pod):
    with pytest.raises(ToolInputError):
        build_logql(namespace="shop", pod=pod, app=None, contains=None, errors_only=False)
