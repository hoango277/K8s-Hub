"""Tests for the LangGraph event -> SSE translation layer.

This is the part most likely to break when upgrading LangGraph: event names
change, the shape of `data` changes, and when it breaks there is NO exception
— the chat panel just silently shows nothing. The tests here build fake event
streams to catch that without calling a real model.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.integrations.llm.streaming import (
    StreamCollector,
    _reasoning_of,
    _text_of,
    stream_graph_events,
)
from app.schemas.events import EventStream


class FakeGraph:
    """Fake graph that emits exactly the list of events it was given."""

    def __init__(self, events: list[dict[str, Any]], error: Exception | None = None):
        self._events = events
        self._error = error

    async def astream_events(self, state, config=None, version="v2"):  # noqa: ARG002
        for e in self._events:
            yield e
        if self._error is not None:
            raise self._error


def token(text: str) -> dict[str, Any]:
    return {
        "event": "on_chat_model_stream",
        "name": "model",
        "run_id": "r1",
        "data": {"chunk": AIMessageChunk(content=text)},
    }


def tool_start(run_id: str, name: str, args: dict) -> dict[str, Any]:
    return {
        "event": "on_tool_start",
        "name": name,
        "run_id": run_id,
        "data": {"input": args},
    }


def tool_end(run_id: str, content: str, status: str = "success") -> dict[str, Any]:
    return {
        "event": "on_tool_end",
        "name": "tool",
        "run_id": run_id,
        "data": {
            "output": ToolMessage(content=content, tool_call_id=run_id, status=status)
        },
    }


async def run(events, error=None) -> tuple[list[dict], StreamCollector]:
    stream = EventStream()
    collector = StreamCollector()
    frames = [
        f
        async for f in stream_graph_events(
            FakeGraph(events, error), {"messages": []}, stream=stream, collector=collector
        )
    ]
    return frames, collector


def kinds(frames: list[dict]) -> list[str]:
    return [f["event"] for f in frames]


def payload(frame: dict) -> dict:
    return json.loads(frame["data"])


# --------------------------------------------------------------------------


async def test_tokens_are_joined_in_order():
    frames, collector = await run([token("Hello"), token(" there"), token(" friend")])

    assert kinds(frames) == ["token", "token", "token"]
    assert [payload(f)["content"] for f in frames] == ["Hello", " there", " friend"]
    assert collector.content == "Hello there friend"


async def test_seq_increases_from_1():
    frames, _ = await run([token("a"), token("b"), token("c")])

    assert [payload(f)["seq"] for f in frames] == [1, 2, 3]
    # The SSE frame `id` must equal seq so the client can resume after a disconnect.
    assert [f["id"] for f in frames] == ["1", "2", "3"]


async def test_empty_tokens_are_not_sent():
    """Models often emit empty chunks while building a tool-call request."""
    frames, collector = await run([token(""), token("a"), token("")])

    assert kinds(frames) == ["token"]
    assert collector.content == "a"


async def test_tool_call_start_and_end_are_paired():
    frames, collector = await run(
        [
            tool_start("abc", "list_pods", {"namespace": "default"}),
            tool_end("abc", "3 pods"),
        ]
    )

    assert kinds(frames) == ["tool_call_start", "tool_call_end"]

    start, end = payload(frames[0]), payload(frames[1])
    assert start["id"] == end["id"] == "abc"
    assert start["name"] == "list_pods"
    assert start["args"] == {"namespace": "default"}
    assert end["status"] == "ok"
    assert end["result"] == "3 pods"
    assert end["duration_ms"] >= 0

    assert len(collector.tool_calls) == 1
    assert collector.tool_calls[0].status == "ok"


async def test_failed_tool_is_marked_as_error():
    """ToolNode swallows the exception and returns a ToolMessage with status='error'.

    If that field isn't detected, the tool error is displayed like a normal
    result — the user believes the lookup succeeded.
    """
    frames, collector = await run(
        [tool_start("x", "get_logs", {}), tool_end("x", "pod not found", "error")]
    )

    end = payload(frames[1])
    assert end["status"] == "error"
    assert end["error"] == "pod not found"
    assert "result" not in end  # exclude_none: empty fields are not sent

    assert collector.tool_calls[0].status == "error"
    assert collector.tool_calls[0].result is None


async def test_nested_tool_calls():
    frames, _ = await run(
        [
            tool_start("a", "t1", {}),
            tool_start("b", "t2", {}),
            tool_end("b", "done b"),
            tool_end("a", "done a"),
        ]
    )

    results = {payload(f)["id"]: payload(f).get("result") for f in frames[2:]}
    assert results == {"b": "done b", "a": "done a"}


async def test_tool_that_never_finishes_is_marked_as_error():
    """The stream broke before the tool returned a result — it must not be left
    hanging forever in the 'running' state in the database."""
    _, collector = await run([tool_start("a", "t1", {})])

    assert collector.tool_calls[0].status == "error"
    assert collector.tool_calls[0].duration_ms is not None


async def test_unpaired_end_is_ignored():
    frames, collector = await run([tool_end("stray", "some random result")])

    assert frames == []
    assert collector.tool_calls == []


async def test_mid_stream_error_becomes_error_event():
    frames, collector = await run([token("a")], error=RuntimeError("boom"))

    assert kinds(frames) == ["token", "error"]
    assert payload(frames[1])["code"] == "agent_error"
    assert collector.error is not None
    # What was said before the error must still be kept for saving.
    assert collector.content == "a"


@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    [
        (TimeoutError("too slow"), "llm_timeout", True),
        (RuntimeError("rate limit exceeded (429)"), "llm_rate_limit", True),
        (RuntimeError("invalid api key"), "llm_auth", False),
        (RuntimeError("something happened"), "agent_error", False),
    ],
)
async def test_error_classification(error: Exception, code: str, retryable: bool):
    frames, _ = await run([], error=error)

    d = payload(frames[0])
    assert d["code"] == code
    assert d["retryable"] is retryable


async def test_tokens_accumulate_across_model_calls():
    """A turn with tool calls calls the model several times; token counts must add up."""

    def model_end(prompt: int, completion: int) -> dict[str, Any]:
        msg = AIMessage(content="x")
        msg.usage_metadata = {
            "input_tokens": prompt,
            "output_tokens": completion,
            "total_tokens": prompt + completion,
        }
        return {"event": "on_chat_model_end", "name": "m", "run_id": "r", "data": {"output": msg}}

    _, collector = await run([model_end(100, 20), model_end(300, 50)])

    assert collector.prompt_tokens == 400
    assert collector.completion_tokens == 70


# --------------------------------------------------------------------------
# Extracting text from message content
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("plain string", "plain string"),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        # Reasoning blocks and tool-call blocks are not answer text for the user.
        ([{"type": "thinking", "thinking": "ponder"}, {"type": "text", "text": "out"}], "out"),
        ([{"type": "tool_use", "name": "t", "input": {}}], ""),
        ([], ""),
        (None, ""),
    ],
)
def test_text_of(content, expected):
    assert _text_of(content) == expected


# --------------------------------------------------------------------------
# Reasoning (thinking)
# --------------------------------------------------------------------------


def thinking(text: str) -> dict[str, Any]:
    """A Groq-style reasoning chunk: lives in additional_kwargs."""
    ch = AIMessageChunk(content="")
    ch.additional_kwargs = {"reasoning_content": text}
    return {
        "event": "on_chat_model_stream",
        "name": "model",
        "run_id": "r1",
        "data": {"chunk": ch},
    }


async def test_reasoning_becomes_separate_events():
    frames, collector = await run([thinking("Need to look up "), thinking("the time.")])

    assert kinds(frames) == ["thinking", "thinking"]
    assert collector.reasoning == "Need to look up the time."
    # Reasoning must NOT count as the answer.
    assert collector.content == ""


async def test_reasoning_and_answer_are_not_mixed():
    frames, collector = await run(
        [thinking("The user asks for the time."), token("It is 7am.")]
    )

    assert kinds(frames) == ["thinking", "token"]
    assert collector.reasoning == "The user asks for the time."
    assert collector.content == "It is 7am."


async def test_reasoning_is_kept_when_stream_fails_midway():
    _, collector = await run([thinking("half-finished thought")], error=RuntimeError("boom"))

    assert collector.reasoning == "half-finished thought"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        # Google Gemini: still type='text' but with the thought flag.
        ([{"type": "text", "text": "pondering", "thought": True}], "pondering"),
        # A normal text block is NOT reasoning.
        ([{"type": "text", "text": "the answer"}], ""),
    ],
)
def test_reasoning_of_per_provider(content, expected):
    ch = AIMessageChunk(content=content)
    assert _reasoning_of(ch) == expected


def test_thought_blocks_do_not_leak_into_answer():
    """Gemini marks reasoning with the `thought` flag but still uses type='text'.

    Missing that flag makes the reasoning flow straight into the user's answer.
    """
    content = [
        {"type": "text", "text": "inner thought", "thought": True},
        {"type": "text", "text": "spoken out"},
    ]
    assert _text_of(content) == "spoken out"
