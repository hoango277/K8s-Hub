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

No checkpointer: history is reloaded from the system's own database (the
`messages` table) on every turn. The approval flow doesn't need one either:
a write tool stores the proposal and the turn ENDS; the decision comes later
and is written back into the conversation (app/services/approval_service.py).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.integrations.llm.client import get_llm
from app.modules.nl_command.injection import make_tool_guard
from app.modules.nl_command.prompts import build_system_prompt
from app.modules.nl_command.state import ChatState
from app.modules.nl_command.tools import get_tools

logger = logging.getLogger(__name__)

# Tool rounds (one assistant reply asking for tools + running them) allowed
# per turn. When they run out, the model is asked ONE more time without tools
# and must answer with what it found — instead of the turn dying on
# LangGraph's recursion limit with an error and nothing to show for it.
MAX_TOOL_ROUNDS = 10

# Hard backstop, above the budget: each round is 2 graph steps (assistant +
# tools), plus the final tool-less answer.
RECURSION_LIMIT = MAX_TOOL_ROUNDS * 2 + 5

# Seen on lab1 with gpt-oss: asked to create a pod, the model pasted the
# manifest and wrote "sending the proposal for approval…" — but never called
# apply_manifest, so no approval card existed and nothing could be approved.
# Detected on the final answer and corrected ONCE per turn.
NARRATED_CHANGE = re.compile(
    r"```ya?ml[\s\S]*?apiVersion:[\s\S]*?kind:"
    r"|\b(sending|submitting) (the |a |this )?(proposal|change|manifest)"
    r"|\bi(?: will|'ll|'m going to) (propose|submit) (it|this|the change)"
    r"|đang gửi đề xuất|gửi đề xuất tới|sẽ gửi đề xuất",
    re.IGNORECASE,
)
NOT_CALLED = (
    "Your reply describes a cluster change, but you did not call any write tool, so NOTHING was "
    "proposed: no approval card exists. If you have what you need, call the write tool now "
    "(e.g. apply_manifest) instead of describing it. If the change was already proposed earlier, "
    "or you still need details from the user, answer briefly without calling a tool."
)
NUDGED = "k8s_hub_nudged"

OUT_OF_BUDGET = (
    "You have used all the tool calls allowed for this question. Do NOT call any tool. "
    "Answer now with what you found, say clearly what is still unknown, and suggest what "
    "to check next."
)


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
    write_tools = _write_tool_names(tool_list)

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
        messages = [system_message, *state["messages"]]
        if tool_list and _tool_rounds(state["messages"]) >= MAX_TOOL_ROUNDS:
            logger.warning("Tool budget of %d rounds used up; forcing an answer", MAX_TOOL_ROUNDS)
            reply = await llm.ainvoke([*messages, SystemMessage(content=OUT_OF_BUDGET)], config)
            return {"messages": [reply]}
        try:
            reply = await bound_llm.ainvoke(messages, config)
        except Exception as exc:
            if not _is_unknown_tool_error(exc):
                raise
            # The model called a tool that isn't in the list — gpt-oss on Groq
            # does this with tool names from its training ("repo_browser.
            # open_file"), and Groq rejects the whole response. One corrected
            # retry usually recovers; without it the turn is simply lost.
            logger.warning("Model called an unknown tool, retrying once: %s", exc)
            names = ", ".join(t.name for t in tool_list)
            nudge = SystemMessage(
                content=(
                    "Your previous reply called a tool that does not exist. Call ONLY these "
                    f"tools: {names}. To read a file of a skill, use read_skill_file."
                )
            )
            reply = await bound_llm.ainvoke([*messages, nudge], config)

        if write_tools and _narrates_without_calling(reply, state["messages"], write_tools):
            logger.warning("Model described a change without calling a write tool; nudging once")
            retry = await bound_llm.ainvoke(
                [*messages, reply, SystemMessage(content=NOT_CALLED)], config
            )
            retry.additional_kwargs[NUDGED] = True
            return {"messages": [reply, retry]}
        return {"messages": [reply]}

    graph = StateGraph(ChatState)
    graph.add_node("assistant", assistant)
    graph.add_edge(START, "assistant")

    if tool_list:
        # Every tool call passes through the injection guard: cluster data comes
        # back marked untrusted (and flagged when it talks to the model), and a
        # proposal remembers what the user actually asked (injection.py).
        guard = make_tool_guard(
            untrusted=_registry_tool_names(tool_list), write_tools=write_tools
        )
        graph.add_node("tools", ToolNode(tool_list, awrap_tool_call=guard))
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


def _write_tool_names(tools: Sequence[BaseTool]) -> set[str]:
    """Tools that propose changes: built-in WRITE/DESTRUCTIVE ones and custom CLI tools."""
    from app.modules.tools.registry import registry
    from app.modules.tools.schema import Danger

    names = set()
    for t in tools:
        spec = registry.get(t.name)
        if spec is not None and spec.danger is not Danger.READ:
            names.add(t.name)
    return names


def _registry_tool_names(tools: Sequence[BaseTool]) -> set[str]:
    """Tools that return cluster or external data: everything in the tool
    registry (built-in, custom CLI, MCP). The core and skill tools are not
    there — their output is K8s-Hub's own or an engineer's written skill."""
    from app.modules.tools.registry import registry

    return {t.name for t in tools if registry.get(t.name) is not None}


def _this_turn(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Messages since the user's last question."""
    out: list[AnyMessage] = []
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        out.append(message)
    return out


def _narrates_without_calling(
    reply: AnyMessage, messages: Sequence[AnyMessage], write_tools: set[str]
) -> bool:
    if not isinstance(reply, AIMessage) or reply.tool_calls:
        return False
    text = reply.content if isinstance(reply.content, str) else str(reply.content)
    if not NARRATED_CHANGE.search(text):
        return False
    # Asking the user for details is the RIGHT move when something is missing
    # (Qwen on lab1: "the namespace doesn't exist — which tag? limits?"); an
    # earlier, broader pattern nudged that and cost a second slow model call.
    if "?" in text[-400:]:
        return False
    for m in _this_turn(messages):
        if isinstance(m, AIMessage):
            if m.additional_kwargs.get(NUDGED):
                return False  # once per turn
            if any(tc["name"] in write_tools for tc in m.tool_calls):
                return False  # it did propose
    return True


def _tool_rounds(messages: Sequence[AnyMessage]) -> int:
    """Assistant replies that asked for tools since the user's last question."""
    rounds = 0
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            break
        if isinstance(message, AIMessage) and message.tool_calls:
            rounds += 1
    return rounds


def _is_unknown_tool_error(exc: Exception) -> bool:
    """The provider rejected a call to a tool that wasn't offered (Groq: 400
    "tool call validation failed ... which was not in request.tools")."""
    text = str(exc).lower()
    return "not in request.tools" in text or "tool call validation failed" in text


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
    # System notes (an approval decided, a change executed) are folded into the
    # NEXT user message instead of sent as messages of their own: a system
    # message mid-conversation, or two user messages in a row, is rejected by
    # some providers. The current question always comes last, so a note
    # always has a user message to ride on.
    notes: list[str] = []
    for row in rows:
        content = (row.content or "").strip()
        if not content:
            continue
        if row.role == "system":
            notes.append(content)
        elif row.role == "user":
            if notes:
                content = (
                    "[K8s-Hub update since your last reply — from the system, not the user]\n"
                    + "\n".join(notes)
                    + "\n\n"
                    + content
                )
                notes = []
            messages.append(HumanMessage(content=content))
        elif row.role == "assistant" and row.status == "complete":
            messages.append(AIMessage(content=content))
    return messages


__all__ = ["MAX_TOOL_ROUNDS", "RECURSION_LIMIT", "build_chat_graph", "history_to_messages"]
