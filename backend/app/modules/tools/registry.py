"""The one place every tool is looked up — built-in and from MCP servers.

The chat agent, the Tools tab and (later) RCA all ask this registry; none of
them needs to know where a tool came from.

State that can change at runtime (enabled/disabled, the danger level set for
an external tool, the MCP tools discovered) lives in memory here and is
persisted by app/services/tool_service.py, which also reloads it at startup
— the same split as app/core/config.py and settings_service.py, because
`get_tools()` is called synchronously on every chat turn.

Safety defaults:
  - built-in tools are enabled; their danger level is fixed in code;
  - external (MCP) tools start DISABLED and WRITE, whatever the server claims,
    until an engineer reviews them and marks them read-only;
  - only enabled, available READ tools ever reach the chat agent.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import StructuredTool

from app.modules.tools.builtin import kubernetes, logs, metrics, traces
from app.modules.tools.schema import Category, Danger, ToolSpec

BUILTIN: list[ToolSpec] = [
    *kubernetes.TOOLS,
    *metrics.TOOLS,
    *logs.TOOLS,
    *traces.TOOLS,
]

# Tool names providers accept (OpenAI/Groq/Gemini): letters, digits, _ and -, ≤64.
_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def mcp_tool_name(server: str, tool: str) -> str:
    """`<server>__<tool>`: unique across servers, legal as a model tool name."""
    return _TOOL_NAME.sub("_", f"{server}__{tool}")[:64]


@dataclass
class McpToolRecord:
    server_name: str
    server_url: str
    token: str | None
    tool: str
    description: str
    input_schema: dict[str, Any]
    read_only_hint: bool | None


class ToolRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._builtin = {s.name: s for s in BUILTIN}
        self._mcp: dict[str, ToolSpec] = {}
        self._mcp_meta: dict[str, McpToolRecord] = {}
        # name -> enabled; missing means the default (builtin on, MCP off)
        self._enabled: dict[str, bool] = {}
        # name -> danger; only honoured for MCP tools
        self._danger: dict[str, Danger] = {}

    # --- lookup -----------------------------------------------------------

    def all(self) -> list[ToolSpec]:
        with self._lock:
            return [*self._builtin.values(), *self._mcp.values()]

    def get(self, name: str) -> ToolSpec | None:
        with self._lock:
            return self._builtin.get(name) or self._mcp.get(name)

    def is_builtin(self, name: str) -> bool:
        return name in self._builtin

    def mcp_meta(self, name: str) -> McpToolRecord | None:
        return self._mcp_meta.get(name)

    def danger(self, spec: ToolSpec) -> Danger:
        if spec.name in self._builtin:
            return spec.danger
        return self._danger.get(spec.name, Danger.WRITE)

    def is_enabled(self, spec: ToolSpec) -> bool:
        default = spec.name in self._builtin
        return self._enabled.get(spec.name, default)

    def can_run(self, spec: ToolSpec) -> str | None:
        """Why this tool can't run now, or None if it can."""
        if not self.is_enabled(spec):
            return "This tool is disabled."
        if self.danger(spec) is not Danger.READ:
            return (
                "Only read-only tools can run for now: tools that change the cluster "
                "need the approval flow, which isn't built yet."
            )
        return spec.unavailable()

    def chat_tools(self) -> list[Any]:
        return [s.tool for s in self.all() if self.can_run(s) is None]

    # --- runtime state (persisted by tool_service) ---------------------------

    def set_state(
        self, name: str, *, enabled: bool | None = None, danger: Danger | None = None
    ) -> None:
        with self._lock:
            if enabled is not None:
                self._enabled[name] = enabled
            if danger is not None and name not in self._builtin:
                self._danger[name] = danger

    def load_state(self, rows: list[tuple[str, bool, str | None]]) -> None:
        with self._lock:
            self._enabled = {name: enabled for name, enabled, _ in rows}
            self._danger = {name: Danger(d) for name, _, d in rows if d}

    def set_mcp_tools(self, server_name: str, records: list[McpToolRecord]) -> None:
        """Replace every tool of one server (after a refresh, or at startup)."""
        with self._lock:
            for name in [n for n, m in self._mcp_meta.items() if m.server_name == server_name]:
                self._mcp.pop(name, None)
                self._mcp_meta.pop(name, None)
            for rec in records:
                name = mcp_tool_name(server_name, rec.tool)
                self._mcp[name] = ToolSpec(
                    tool=_mcp_tool(name, rec),
                    title=rec.tool,
                    category=Category.EXTERNAL,
                    danger=Danger.WRITE,
                    source=f"mcp:{server_name}",
                )
                self._mcp_meta[name] = rec

    def remove_mcp_server(self, server_name: str) -> None:
        self.set_mcp_tools(server_name, [])


def _mcp_tool(name: str, rec: McpToolRecord) -> StructuredTool:
    from app.modules.tools import mcp_client

    async def run(**kwargs: Any) -> str:
        try:
            return await mcp_client.call_tool(rec.server_url, rec.tool, kwargs, rec.token)
        except mcp_client.McpError as exc:
            return str(exc)

    schema = rec.input_schema or {"type": "object", "properties": {}}
    return StructuredTool(
        name=name,
        description=(rec.description or f"Tool {rec.tool} from MCP server {rec.server_name}.")[
            :1024
        ],
        args_schema=schema,
        coroutine=run,
    )


registry = ToolRegistry()

__all__ = ["BUILTIN", "McpToolRecord", "ToolRegistry", "mcp_tool_name", "registry"]
