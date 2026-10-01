"""The agent recovers once when the model calls a tool that wasn't offered.

Seen on lab1 with gpt-oss on Groq: a skill said "read assets/report-template.md",
the model called its training-time tool `repo_browser.open_file`, and Groq
rejected the whole response ("tool call validation failed … not in
request.tools") — the turn was lost.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.modules.nl_command import agent

GROQ_ERROR = (
    "Error code: 400 - tool call validation failed: attempted to call tool "
    "'repo_browser.open_file' which was not in request.tools"
)


class FakeModel:
    def __init__(self, failures: int, error: str = GROQ_ERROR) -> None:
        self.failures = failures
        self.error = error
        self.calls: list[list] = []

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, config=None):
        self.calls.append(list(messages))
        if len(self.calls) <= self.failures:
            raise RuntimeError(self.error)
        return AIMessage(content="done")


def _graph(monkeypatch, model):
    monkeypatch.setattr(agent, "get_llm", lambda **_: model)
    return agent.build_chat_graph(tools=[])


async def test_retries_once_with_a_nudge(monkeypatch):
    model = FakeModel(failures=1)
    out = await _graph(monkeypatch, model).ainvoke({"messages": [HumanMessage("check ns")]})
    assert out["messages"][-1].content == "done"
    assert len(model.calls) == 2
    nudge = model.calls[1][-1]
    assert isinstance(nudge, SystemMessage) and "does not exist" in nudge.content


async def test_gives_up_after_one_retry(monkeypatch):
    model = FakeModel(failures=2)
    with pytest.raises(RuntimeError, match="not in request.tools"):
        await _graph(monkeypatch, model).ainvoke({"messages": [HumanMessage("x")]})
    assert len(model.calls) == 2


async def test_other_errors_are_not_retried(monkeypatch):
    model = FakeModel(failures=1, error="rate limit exceeded")
    with pytest.raises(RuntimeError, match="rate limit"):
        await _graph(monkeypatch, model).ainvoke({"messages": [HumanMessage("x")]})
    assert len(model.calls) == 1
