"""What a tool is — and how it differs from a skill.

A TOOL is code the model can call: read pods, query metrics, search logs,
explain a trace, propose a change, or a custom CLI tool defined on the web. A SKILL (Agent
Skills standard, app/modules/skills/) is a folder of instructions telling the
agent HOW to use tools for a task. Skills sit on top of tools, not instead.

`ToolSpec` = one LangChain `BaseTool` + what the system needs to know that the
model doesn't: a human title, a category, a danger level, where it came from,
and whether it can run right now. Keeping the tool a plain `BaseTool` means the
same object serves every consumer: the chat agent binds it, the Tools tab runs
it with `ainvoke`, and its JSON schema drives the tab's input form.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from langchain_core.tools import BaseTool


class Danger(StrEnum):
    """What running the tool can do to the cluster.

    READ tools run as soon as they are called. WRITE/DESTRUCTIVE tools never
    change anything themselves: calling one PROPOSES the change, which goes
    through the approval flow (dry-run -> a human approves -> execute ->
    verify -> audit; app/services/approval_service.py). In read_only mode they
    are not offered at all.
    """

    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


class Category(StrEnum):
    KUBERNETES = "kubernetes"
    METRICS = "metrics"
    LOGS = "logs"
    TRACES = "traces"
    CUSTOM = "custom"
    MCP = "mcp"


@dataclass(frozen=True)
class ToolSpec:
    tool: BaseTool
    title: str
    category: Category
    danger: Danger
    #: "builtin", "custom" (a CLI tool defined on the web) or "mcp:<server name>"
    source: str = "builtin"
    #: Returns why the tool can't run now (e.g. "TEMPO_URL is empty"), or None.
    unavailable: Callable[[], str | None] = lambda: None

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return (self.tool.description or "").strip()

    def input_schema(self) -> dict[str, Any]:
        """JSON schema of the arguments, as the model sees them (injected args excluded)."""
        schema = self.tool.tool_call_schema
        if isinstance(schema, dict):
            return {k: v for k, v in schema.items() if k not in ("description", "title")}
        return schema.model_json_schema()


__all__ = ["Category", "Danger", "ToolSpec"]
