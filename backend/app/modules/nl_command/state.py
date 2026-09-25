"""The state the LangGraph graph carries between steps.

There is only one thing: the message list. `add_messages` is LangGraph's
reducer — new messages returned by a node are APPENDED to the old list rather
than overwriting it, and messages with the same id are replaced. Without it,
every tool-calling round would wipe out the preceding context.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """The state of one chat turn."""

    messages: Annotated[list[AnyMessage], add_messages]


__all__ = ["ChatState"]
