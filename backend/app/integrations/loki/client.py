"""Loki HTTP API client - READS logs of the target K8s cluster.

Role: evidence source for the logs tool and for RCA
(app/modules/rca/collectors/logs.py). This app's OWN logs only go to stdout
(app/core/logging.py) — on the cluster Alloy ships them here like any pod.

Runs LogQL it is given; the tool builds that LogQL from validated fields,
never from model text (see app/modules/tools/builtin/logs.py).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT = 15.0


class LokiError(RuntimeError):
    """Unreachable or query rejected. Message is user-facing."""


@dataclass
class LogLine:
    ts_ns: int
    labels: dict[str, str]
    line: str


def _base_url() -> str:
    url = get_settings().LOKI_URL.strip().rstrip("/")
    if not url:
        raise LokiError("No log source is configured (LOKI_URL is empty in .env).")
    return url


async def query_range(logql: str, *, minutes: int, limit: int) -> list[LogLine]:
    """Newest first, at most `limit` lines across all streams."""
    end_ns = time.time_ns()
    params = {
        "query": logql,
        "start": end_ns - minutes * 60 * 1_000_000_000,
        "end": end_ns,
        "limit": limit,
        "direction": "backward",
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{_base_url()}/loki/api/v1/query_range", params=params)
    except httpx.HTTPError as exc:
        raise LokiError(f"Could not reach Loki at {_base_url()}: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise LokiError(f"Loki rejected the query ({resp.status_code}): {resp.text[:300]}")

    data: Any = resp.json().get("data") or {}
    lines = [
        LogLine(ts_ns=int(ts), labels=dict(stream.get("stream") or {}), line=text)
        for stream in data.get("result") or []
        for ts, text in stream.get("values") or []
    ]
    lines.sort(key=lambda entry: -entry.ts_ns)
    return lines[:limit]


__all__ = ["LogLine", "LokiError", "query_range"]
