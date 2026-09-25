"""Translate LangGraph events into events sent to the browser.

LangGraph emits a very detailed event stream (`astream_events`) describing
everything happening inside: the model emitting text, a tool starting, a tool
finishing… But that is the library's internal language, not something that
should leak out — it changes between versions and carries a lot of noise.

This file is the single translation layer between those two worlds. Inside are
LangGraph events, outside is `app/schemas/events.py` — the fixed contract with
the frontend. When LangGraph changes version, only this file has to change.

Besides emitting events, it also COLLECTS the final result (the full answer,
the tool calls, the token counts) into `StreamCollector` so the caller can
write it to the database — without having to listen to the stream a second
time.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.schemas.events import (
    ErrorEvent,
    EventStream,
    ThinkingEvent,
    TokenEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

logger = logging.getLogger(__name__)

# Tool results sent to the browser are truncated: a pod's logs can be hundreds
# of thousands of characters, and pushing all of it down freezes the browser.
# The full version still goes to Langfuse and is still seen by the model — this
# is only the part for DISPLAY.
RESULT_DISPLAY_MAX = 2000


@dataclass
class ToolCallRecord:
    """One tool call, with everything needed to write it to the database."""

    call_id: str
    name: str
    args: dict[str, Any]
    started_at: datetime
    result: str | None = None
    status: str = "running"
    error: str | None = None
    duration_ms: int | None = None

    # Used to compute the duration; the system clock can be adjusted, so we
    # don't take the difference of two datetime stamps.
    _started: float = field(default_factory=time.perf_counter, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "status": self.status,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
        }


@dataclass
class StreamCollector:
    """What remains after the stream has finished."""

    content: str = ""

    # The model's own thinking. Empty when the provider doesn't expose reasoning.
    reasoning: str = ""

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None

    def tool_calls_as_dicts(self) -> list[dict[str, Any]]:
        return [tc.to_dict() for tc in self.tool_calls]


def _text_of(content: Any) -> str:
    """Extract the ANSWER text from message content.

    Each provider returns a different shape: Groq returns a string, Gemini and
    Claude return a list of blocks (text, reasoning, tool-call requests). Only
    text blocks are taken.

    Blocks with the `thought` flag are dropped: Gemini marks reasoning with
    that flag but still uses type='text'. Without dropping them the reasoning
    would leak straight into the answer — the user would read even the guesses
    the model had already rejected.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif (
                isinstance(block, dict)
                and block.get("type") == "text"
                and not block.get("thought")
            ):
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def _reasoning_of(chunk: Any) -> str:
    """Extract the REASONING from a message chunk, if the provider sent any.

    It lives in two different places depending on the provider:
      - Groq / OpenAI-compatible APIs: additional_kwargs['reasoning_content']
      - Google Gemini: content blocks with type='text' plus thought=True

    If there is none, return an empty string — the caller takes that to mean
    this model doesn't expose reasoning, and simply sends no event.
    """
    ak = getattr(chunk, "additional_kwargs", None) or {}
    raw = ak.get("reasoning_content") or ak.get("reasoning")
    if isinstance(raw, str) and raw:
        return raw

    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("thought") and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        return "".join(parts)
    return ""


def _truncate(text: str, limit: int = RESULT_DISPLAY_MAX) -> str:
    if len(text) <= limit:
        return text
    remaining = len(text) - limit
    return f"{text[:limit]}\n… ({remaining} more characters, see the full trace)"


def _tool_result(output: Any) -> tuple[str, bool]:
    """Extract the content and status from a tool's output.

    ToolNode catches tool errors and returns a ToolMessage with status='error'
    instead of raising — that way the model can read the error message and
    handle it itself. It means tool errors do NOT stop the stream; they have
    to be detected here.
    """
    status = getattr(output, "status", None)
    if hasattr(output, "content"):
        return _text_of(output.content) or str(output.content), status == "error"
    return str(output), False


async def stream_graph_events(
    graph: Any,
    state: dict[str, Any],
    *,
    stream: EventStream,
    collector: StreamCollector,
    config: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Run the graph and yield SSE frames in real time.

    The final result is written into `collector`; this function only yields
    frames to send. Errors become an `ErrorEvent` rather than being raised,
    because once the SSE stream is open the HTTP status can no longer change —
    reporting the error as data is the only way for the client to know what
    happened.
    """
    running: dict[str, ToolCallRecord] = {}
    text_parts: list[str] = []
    reasoning_parts: list[str] = []

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            kind = event["event"]

            # --- The model is emitting text ---
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]

                # Reasoning first, since it arrives before the answer. The two
                # travel on separate paths and must NOT be mixed together.
                reasoning = _reasoning_of(chunk)
                if reasoning:
                    reasoning_parts.append(reasoning)
                    yield stream.emit(ThinkingEvent(content=reasoning))

                text = _text_of(getattr(chunk, "content", ""))
                if text:
                    text_parts.append(text)
                    yield stream.emit(TokenEvent(content=text))

            # --- The model finished a turn: read the token counts ---
            elif kind == "on_chat_model_end":
                usage = getattr(event["data"].get("output"), "usage_metadata", None)
                if usage:
                    # One turn can call the model several times (each tool round
                    # is one call), so accumulate instead of overwriting.
                    collector.prompt_tokens = (collector.prompt_tokens or 0) + int(
                        usage.get("input_tokens", 0)
                    )
                    collector.completion_tokens = (
                        collector.completion_tokens or 0
                    ) + int(usage.get("output_tokens", 0))

            # --- A tool starts running ---
            elif kind == "on_tool_start":
                call_id = str(event["run_id"])
                args = event["data"].get("input") or {}
                if not isinstance(args, dict):
                    args = {"input": str(args)}

                record = ToolCallRecord(
                    call_id=call_id,
                    name=event["name"],
                    args=args,
                    started_at=datetime.now(UTC),
                )
                running[call_id] = record
                collector.tool_calls.append(record)

                yield stream.emit(
                    ToolCallStartEvent(id=call_id, name=record.name, args=args)
                )

            # --- The tool finished ---
            elif kind == "on_tool_end":
                call_id = str(event["run_id"])
                record = running.pop(call_id, None)
                if record is None:
                    # No matching start — skip it; even if sent, the client
                    # wouldn't know what to attach it to.
                    logger.warning("Got on_tool_end without on_tool_start: %s", call_id)
                    continue

                content, is_error = _tool_result(event["data"].get("output"))
                record.duration_ms = int(
                    (time.perf_counter() - record._started) * 1000
                )
                record.status = "error" if is_error else "ok"
                if is_error:
                    record.error = _truncate(content)
                else:
                    record.result = _truncate(content)

                yield stream.emit(
                    ToolCallEndEvent(
                        id=call_id,
                        status=record.status,
                        duration_ms=record.duration_ms,
                        result=record.result,
                        error=record.error,
                    )
                )

    except asyncio.CancelledError:
        # The user closed the tab or pressed stop. Not an error — let the
        # caller take care of saving what was said so far.
        collector.content = "".join(text_parts)
        collector.reasoning = "".join(reasoning_parts)
        raise

    except Exception as exc:
        logger.exception("Chat stream failed")
        collector.error = f"{type(exc).__name__}: {exc}"
        yield stream.emit(
            ErrorEvent(
                code=_error_code(exc),
                message=_error_message(exc),
                retryable=_is_retryable(exc),
            )
        )

    finally:
        collector.content = "".join(text_parts)
        collector.reasoning = "".join(reasoning_parts)

        # Any tool that was opened but never closed is marked as an error, so
        # it doesn't sit forever in the "running" state in the database.
        for record in running.values():
            record.status = "error"
            record.error = "The stream ended before the tool returned a result"
            record.duration_ms = int((time.perf_counter() - record._started) * 1000)


# --------------------------------------------------------------------------
# Error classification — so the client knows what to show and whether to
# offer a retry
# --------------------------------------------------------------------------


def _error_code(exc: Exception) -> str:
    type_name = type(exc).__name__.lower()
    text = str(exc).lower()

    if "timeout" in type_name or "timeout" in text:
        return "llm_timeout"
    if "ratelimit" in type_name or "rate limit" in text or "429" in text:
        return "llm_rate_limit"
    if "authentication" in type_name or "api key" in text or "401" in text:
        return "llm_auth"
    if "recursion" in type_name or "recursion" in text:
        return "agent_loop"
    return "agent_error"


def _error_message(exc: Exception) -> str:
    """The sentence shown to the user. Technical details go to the server log."""
    code = _error_code(exc)
    return {
        "llm_timeout": "The model took too long to respond. Try again or switch to a faster model.",
        "llm_rate_limit": "Hit the provider's rate limit. Wait a moment and try again.",
        "llm_auth": "Invalid API key. Check it in Settings.",
        "agent_loop": (
            "The assistant called tools too many times without reaching an answer. "
            "Try a more specific question."
        ),
    }.get(code, f"Error while processing: {exc}")


def _is_retryable(exc: Exception) -> bool:
    return _error_code(exc) in {"llm_timeout", "llm_rate_limit"}


__all__ = [
    "RESULT_DISPLAY_MAX",
    "StreamCollector",
    "ToolCallRecord",
    "stream_graph_events",
]
