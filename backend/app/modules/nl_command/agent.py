"""The graph that handles one chat turn.

The loop is very short:

    user asks -> [assistant] -> tool call? -> [tools] -> [assistant] -> answer

`tools_condition` decides the branch: if the model's reply includes a tool-call
request, go on to the tools node, otherwise finish. The loop runs until the
model stops asking for tools.

Why LangGraph instead of a hand-written while loop: LangGraph emits detailed
events for every step (`astream_events`), and that is exactly what lets the
chat panel show "calling tool X" in real time. Writing it by hand would mean
rebuilding all of that.

No checkpointer yet: history is reloaded from the system's own database
(the `messages` table) on every turn, so LangGraph doesn't need to remember it
for us. A checkpointer only becomes necessary with the action approval step —
which needs to pause midway and resume later.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.integrations.llm.client import get_llm
from app.modules.nl_command.prompts import build_system_prompt
from app.modules.nl_command.state import ChatState
from app.modules.nl_command.tools import get_tools

logger = logging.getLogger(__name__)

# Stops the tool-calling loop from running forever. Each round is 2 steps
# (assistant + tools), so this number allows about 12 tool calls per turn.
RECURSION_LIMIT = 25


def build_chat_graph(
    *,
    provider: str | None = None,
    model: str | None = None,
    tools: Sequence[BaseTool] | None = None,
) -> Any:
    """Build the graph for one chat turn.

    Args:
        provider: Force the provider for this turn. If empty, follow the configuration.
        model:    Force the model name for this turn.
        tools:    Force the tool list. Mainly used by tests.
    """
    tool_list = list(get_tools() if tools is None else tools)
    llm = get_llm(provider=provider, model=model)

    # With no tools, don't call bind_tools — some providers raise an error when
    # given an empty list.
    bound_llm = llm.bind_tools(tool_list) if tool_list else llm

    system_message = SystemMessage(content=build_system_prompt(tool_list))

    async def assistant(state: ChatState, config: RunnableConfig) -> dict[str, list[AnyMessage]]:
        """Ask the model.

        The system prompt is prepended here rather than stored in the state —
        if it were stored, every tool-calling round would add another copy.

        Passing `config` down to `ainvoke` is MANDATORY, don't drop it to tidy
        up. From Python 3.11 on, LangChain propagates config through
        contextvars, so forgetting it still works, but on 3.10 it does NOT: the
        model runs detached from the event stream, and as a result the chat
        panel receives no text at all, only sees the tools running. That bug
        raises no exception, streaming just silently disappears — very easy to
        mistake for a provider problem. This is also why the project sets its
        Python floor at 3.11 (see pyproject.toml).
        """
        reply = await bound_llm.ainvoke([system_message, *state["messages"]], config)
        return {"messages": [reply]}

    graph = StateGraph(ChatState)
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")

    if tool_list:
        graph.add_node("tools", ToolNode(tool_list))
        # tools_condition returns "tools" when the model asks for a tool, END otherwise.
        graph.add_conditional_edges(
            "assistant",
            tools_condition,
            {"tools": "tools", END: END},
        )
        graph.add_edge("tools", "assistant")
    else:
        graph.add_edge("assistant", END)

    return graph.compile()


def history_to_messages(rows: Iterable[Any]) -> list[AnyMessage]:
    """Convert history from the database into messages for the model.

    ONLY the user's and assistant's text is taken. Tool calls from previous
    turns are deliberately skipped: resending them would require sending BOTH
    halves of each call request / result pair, and if either half is missing
    the provider returns an error. Old lookup results are usually stale anyway
    — making the assistant look things up again is more correct than letting
    it trust numbers from ten minutes ago.
    """
    messages: list[AnyMessage] = []
    for row in rows:
        content = (row.content or "").strip()
        if not content:
            continue
        if row.role == "user":
            messages.append(HumanMessage(content=content))
        elif row.role == "assistant" and row.status == "complete":
            messages.append(AIMessage(content=content))
    return messages


__all__ = ["RECURSION_LIMIT", "build_chat_graph", "history_to_messages"]
