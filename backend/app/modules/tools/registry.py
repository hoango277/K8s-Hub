"""The one place every tool is looked up — built-in, custom and MCP.

The chat agent, the Tools tab and (later) RCA all ask this registry; none of
them needs to know where a tool came from.

State that can change at runtime (enabled/disabled, the custom tools) lives
in memory here and is persisted by app/services/tool_service.py, which also
reloads it at startup — the same split as app/core/config.py and
settings_service.py, because `get_tools()` is called synchronously on every
chat turn.

Rules:
  - built-in tools are enabled by default; their danger level is fixed in code;
  - WRITE/DESTRUCTIVE tools only propose (approval flow) and are offered only
    when K8S_EXECUTION_MODE isn't read_only (their `unavailable` says so);
  - custom tools are enabled/disabled on their own row (`custom_tools.enabled`);
  - MCP tools carry their own policy (`mcp_tools.enabled`, `requires_approval`),
    set by engineers; new ones start disabled and requiring approval (mcp.py).
"""

from __future__ import annotations

import threading
from typing import Any

from app.modules.tools import mcp
from app.modules.tools.builtin import actions, kubernetes, logs, metrics, rca, resources, traces
from app.modules.tools.custom import CustomToolDef, build_spec
from app.modules.tools.schema import ToolSpec

BUILTIN: list[ToolSpec] = [
    *kubernetes.TOOLS,
    *resources.TOOLS,
    *metrics.TOOLS,
    *logs.TOOLS,
    *traces.TOOLS,
    *rca.TOOLS,
    *actions.TOOLS,
]


class ToolRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._builtin = {s.name: s for s in BUILTIN}
        self._custom: dict[str, ToolSpec] = {}
        self._custom_defs: dict[str, CustomToolDef] = {}
        # name -> enabled, for built-in tools; missing means enabled.
        self._enabled: dict[str, bool] = {}
        self._mcp: dict[str, ToolSpec] = {}
        self._mcp_records: dict[str, mcp.McpToolRecord] = {}

    # --- lookup -----------------------------------------------------------

    def all(self) -> list[ToolSpec]:
        with self._lock:
            return [*self._builtin.values(), *self._custom.values(), *self._mcp.values()]

    def get(self, name: str) -> ToolSpec | None:
        with self._lock:
            return self._builtin.get(name) or self._custom.get(name) or self._mcp.get(name)

    def is_builtin(self, name: str) -> bool:
        return name in self._builtin

    def custom_def(self, name: str) -> CustomToolDef | None:
        return self._custom_defs.get(name)

    def mcp_record(self, name: str) -> mcp.McpToolRecord | None:
        return self._mcp_records.get(name)

    def is_enabled(self, spec: ToolSpec) -> bool:
        record = self._mcp_records.get(spec.name)
        if record is not None:
            return record.enabled
        custom = self._custom_defs.get(spec.name)
        if custom is not None:
            return custom.enabled
        return self._enabled.get(spec.name, True)

    def can_run(self, spec: ToolSpec) -> str | None:
        """Why this tool can't run now, or None if it can."""
        if not self.is_enabled(spec):
            return "This tool is disabled."
        return spec.unavailable()

    def chat_tools(self) -> list[Any]:
        return [s.tool for s in self.all() if self.can_run(s) is None]

    # --- runtime state (persisted by tool_service) ---------------------------

    def set_enabled(self, name: str, enabled: bool) -> None:
        with self._lock:
            if name in self._mcp_records:
                self.set_mcp_policy(name, enabled=enabled)
                return
            custom = self._custom_defs.get(name)
            if custom is not None:
                custom.enabled = enabled
            else:
                self._enabled[name] = enabled

    def load_state(self, rows: list[tuple[str, bool]]) -> None:
        with self._lock:
            self._enabled = dict(rows)

    def set_custom_tools(self, defs: list[CustomToolDef]) -> None:
        """Replace every custom tool (at startup, and after each edit)."""
        with self._lock:
            self._custom_defs = {d.name: d for d in defs}
            self._custom = {d.name: build_spec(d) for d in defs}

    def upsert_custom(self, d: CustomToolDef) -> None:
        with self._lock:
            self._custom_defs[d.name] = d
            self._custom[d.name] = build_spec(d)

    def remove_custom(self, name: str) -> None:
        with self._lock:
            self._custom_defs.pop(name, None)
            self._custom.pop(name, None)

    def set_mcp_tools(self, server_name: str, records: list[mcp.McpToolRecord]) -> None:
        """Replace every tool of one server (after a refresh, or at startup)."""
        with self._lock:
            for name in [n for n, r in self._mcp_records.items() if r.server_name == server_name]:
                self._mcp.pop(name, None)
                self._mcp_records.pop(name, None)
            for rec in records:
                self._mcp_records[rec.name] = rec
                self._mcp[rec.name] = mcp.build_spec(rec)

    def remove_mcp_server(self, server_name: str) -> None:
        self.set_mcp_tools(server_name, [])

    def set_mcp_policy(
        self, name: str, *, enabled: bool | None = None, requires_approval: bool | None = None
    ) -> None:
        """Change one MCP tool's policy; the spec is rebuilt so the catalog and
        the description the model reads say the same thing."""
        with self._lock:
            rec = self._mcp_records.get(name)
            if rec is None:
                return
            if enabled is not None:
                rec.enabled = enabled
            if requires_approval is not None:
                rec.requires_approval = requires_approval
            self._mcp[name] = mcp.build_spec(rec)


registry = ToolRegistry()

__all__ = ["BUILTIN", "ToolRegistry", "registry"]
