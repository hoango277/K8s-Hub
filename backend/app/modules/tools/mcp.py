"""Tools of external MCP servers, each behind a policy an engineer sets.

Re-added on 01/10/2026 (removed the day before) with two rules:

  - only engineers and admins connect servers and set policies
    (app/api/v1/tools.py, `require_role("engineer")`);
  - every tool has `enabled` and `requires_approval`. New tools start
    disabled and requiring approval, whatever the server claims — its
    `readOnlyHint` is shown as a hint, never trusted.

A tool requiring approval doesn't call the server when the model calls it: it
stores a pending approval with the exact call (app/services/approval_service.py),
and the server is called only after an engineer approves. A tool an engineer
marked "no approval" is called directly.

The policy is read from the registry AT CALL TIME, so switching a tool back to
"requires approval" applies to the very next call — including a chat turn
that is already running.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from app.modules.tools.schema import Category, Danger, ToolSpec

# Tool names providers accept (OpenAI/Groq/Gemini): letters, digits, _ and -, ≤64.
_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]+")


def mcp_tool_name(server: str, tool: str) -> str:
    """`<server>__<tool>`: unique across servers, legal as a model tool name."""
    return _TOOL_NAME.sub("_", f"{server}__{tool}")[:64]


@dataclass
class McpToolRecord:
    server_id: str
    server_name: str
    server_url: str
    tool: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    read_only_hint: bool | None = None
    enabled: bool = False
    requires_approval: bool = True

    @property
    def name(self) -> str:
        return mcp_tool_name(self.server_name, self.tool)


def build_spec(rec: McpToolRecord) -> ToolSpec:
    name = rec.name

    async def run(config: RunnableConfig, **kwargs: Any) -> str:
        from app.modules.nl_command.planner import plan_mcp
        from app.modules.tools import mcp_client
        from app.modules.tools.builtin.actions import propose
        from app.modules.tools.registry import registry

        current = registry.mcp_record(name)  # the policy NOW, not when built
        if current is None or not current.enabled:
            return f"The MCP tool {name} is disabled."
        if current.requires_approval:

            async def build():  # noqa: ANN202 - matches propose()'s callable
                return plan_mcp(
                    server_id=current.server_id,
                    server=current.server_name,
                    url=current.server_url,
                    tool=current.tool,
                    args=kwargs,
                )

            return await propose(build, source=name, config=config)

        from app.services import tool_service

        try:
            token = await tool_service.server_token(current.server_id)
            return await mcp_client.call_tool(current.server_url, current.tool, kwargs, token)
        except (mcp_client.McpError, LookupError) as exc:
            return str(exc)

    schema = rec.input_schema or {"type": "object", "properties": {}}
    approval = (
        "Each call waits for an engineer's approval before it runs."
        if rec.requires_approval
        else "Runs directly."
    )
    tool = StructuredTool(
        name=name,
        description=(
            f"{rec.description or f'Tool {rec.tool}'} (external MCP server {rec.server_name}; "
            f"{approval})"
        )[:1024],
        args_schema=schema,
        coroutine=run,
    )
    return ToolSpec(
        tool=tool,
        title=rec.tool,
        category=Category.MCP,
        # What the catalog shows: a tool that runs without approval is treated as
        # read-only by the engineer who decided so; everything else as a change.
        danger=Danger.WRITE if rec.requires_approval else Danger.READ,
        source=f"mcp:{rec.server_name}",
    )


__all__ = ["McpToolRecord", "build_spec", "mcp_tool_name"]
