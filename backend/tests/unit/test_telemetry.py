"""Tests for self-monitoring: JSON log lines and the /metrics endpoint."""

from __future__ import annotations

import json
import logging
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import telemetry
from app.core.logging import JsonFormatter


def _record(
    name: str = "app.test", level: int = logging.INFO, msg: str = "hello"
) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, None, None)


def test_json_lines_carry_level_logger_message_and_extras():
    record = _record(msg="turn done")
    record.trace_id = "abc"
    data = json.loads(JsonFormatter().format(record))
    assert data == {
        "level": "info",
        "logger": "app.test",
        "message": "turn done",
        "trace_id": "abc",
    }


def test_json_lines_include_the_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    record = logging.LogRecord("app.test", logging.ERROR, __file__, 1, "failed", None, exc_info)
    data = json.loads(JsonFormatter().format(record))
    assert data["level"] == "error"
    assert "ValueError: boom" in data["exception"]


def test_metrics_endpoint_exposes_chat_metrics():
    app = FastAPI()
    telemetry.setup_metrics(app)
    telemetry.record_chat_turn(
        provider="groq",
        model="m",
        outcome="ok",
        seconds=1.5,
    )
    body = TestClient(app).get("/metrics").text
    assert 'k8shub_chat_turns_total{model="m",outcome="ok",provider="groq"}' in body
    assert 'k8shub_chat_turn_duration_seconds_count{provider="groq"}' in body
    # AI usage (tokens, tool calls) lives in Langfuse only — never duplicated here.
    assert "k8shub_llm_tokens_total" not in body
    assert "k8shub_tool_calls_total" not in body
    assert "k8shub_chat_streams_active" in body
