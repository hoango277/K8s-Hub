"""Tools the assistant is allowed to call from the chat panel.

THIS IS THE ONLY ATTACHMENT POINT. To let the assistant do something new, add
a tool to `get_tools()` — don't modify the graph and don't modify the
streaming layer.

Safety boundaries — read carefully before adding one:

  1. Tools in this file are READ-ONLY. No tool creates/edits/deletes resources
     on the cluster. Mutations go through a separate path: the assistant
     proposes a structured description, the system dry-runs it, a human
     approves, and only then is it executed.
  2. No raw command strings. There is no tool like `run_kubectl(cmd)` —
     parameters must be discrete fields so they can be checked before running.
  3. The tool description is what the model reads to decide whether to call
     it. Write a vague description and the model will call it at the wrong
     time, and that bug is very hard to track down.

Cluster lookups (pods, events, logs, metrics, traces) are SKILLS, not tools
defined here: they live in app/modules/tools/ so they appear in the Skills
catalog and can be switched off. This file keeps the two core tools that only
describe the system itself.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings
from app.integrations.llm.client import describe_config


@tool
def system_info(config: RunnableConfig) -> str:
    """Report how the K8s Hub system is currently configured.

    Use when the user asks which AI model the system is running, which
    execution mode it is in, or which namespaces it is allowed to act on.
    """
    # `config` is injected by LangChain and is NOT in the schema the model sees
    # — so the model cannot (and need not) pass anything for this parameter.
    #
    # The provider and model are taken from here rather than from the global
    # configuration: users can pick a model for a SINGLE chat turn. Reading the
    # global configuration would make the assistant misreport itself right
    # after the user switched models in the UI.
    meta = (config or {}).get("metadata") or {}
    llm = describe_config(
        provider=meta.get("llm_provider"), model=meta.get("llm_model")
    )

    settings = get_settings()

    mode_description = {
        "read_only": "read-only, no changes are made",
        "require_approval": "changes must be approved by a human before running",
        "auto": "changes are applied automatically, WITHOUT human approval",
    }.get(settings.K8S_EXECUTION_MODE, settings.K8S_EXECUTION_MODE)

    namespaces = settings.K8S_ALLOWED_NAMESPACES or ["(all)"]

    return (
        f"AI model: {llm['provider']} / {llm['model']}\n"
        f"Tool calling: {'yes' if llm['tool_calling'] else 'no'}\n"
        f"Execution mode: {settings.K8S_EXECUTION_MODE} — {mode_description}\n"
        f"Allowed namespaces: {', '.join(namespaces)}\n"
        f"Data sources: Prometheus {settings.PROMETHEUS_URL}, Loki {settings.LOKI_URL}, "
        f"Tempo {settings.TEMPO_URL or '(not configured)'}\n"
        f"Environment: {settings.APP_ENV}"
    )


@tool
def current_time() -> str:
    """The current time in UTC.

    Use when you need to compute time spans, e.g. how long ago a pod restarted,
    or which time range to fetch logs for.
    """
    now = datetime.now(UTC)
    return f"{now.isoformat(timespec='seconds')} (UTC)"


# Always available: they only describe the system itself. Everything that reads
# the cluster is a TOOL in app/modules/tools/ (can be switched off on the Tools
# tab); SKILLS (app/modules/skills/) are instructions on top of those tools.
CORE_TOOLS: list[BaseTool] = [system_info, current_time]


def get_tools() -> list[BaseTool]:
    """The tool list for one chat turn: core tools, the three skill tools (when
    any skill is enabled), and every enabled, runnable read-only tool.

    Asked per turn (not cached) so a tool or skill switched off on the Skills
    page applies to the very next question.
    """
    from app.modules.skills.agent_tools import skill_tools
    from app.modules.tools.registry import registry

    return [*CORE_TOOLS, *skill_tools(), *registry.chat_tools()]


__all__ = ["CORE_TOOLS", "get_tools"]
