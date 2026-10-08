"""Prometheus HTTP API client - READS metrics of the target K8s cluster.

Role: evidence source for the metrics tool and for RCA
(app/modules/rca/collectors/metrics.py). NOT this app's own /metrics — that is
app/core/telemetry.py.

This module runs PromQL it is given. It does NOT accept PromQL from the model:
the tool (app/modules/tools/builtin/metrics.py) builds queries from
fixed templates with validated names, same rule as TraceQL for Tempo.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import get_settings

TIMEOUT = 15.0


class PrometheusError(RuntimeError):
    """Unreachable or query rejected. Message is user-facing."""


def _base_url() -> str:
    url = get_settings().PROMETHEUS_URL.strip().rstrip("/")
    if not url:
        raise PrometheusError("No metrics source is configured (PROMETHEUS_URL is empty in .env).")
    return url


async def _get(path: str, params: dict[str, Any]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{_base_url()}{path}", params=params)
    except httpx.HTTPError as exc:
        raise PrometheusError(
            f"Could not reach Prometheus at {_base_url()}: {type(exc).__name__}"
        ) from exc
    body = (
        resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    )
    if resp.status_code != 200 or body.get("status") != "success":
        raise PrometheusError(
            f"Prometheus rejected the query: {body.get('error') or resp.status_code}"
        )
    return body["data"]


async def query(promql: str, *, at: float | None = None) -> list[dict[str, Any]]:
    """Instant query -> [{"metric": {...}, "value": [ts, "v"]}, ...].

    `at` (unix seconds) evaluates it at a past moment — RCA looks at an
    incident window, not only at "now"."""
    params: dict[str, Any] = {"query": promql}
    if at is not None:
        params["time"] = at
    data = await _get("/api/v1/query", params)
    return list(data.get("result") or [])


async def query_range(
    promql: str, *, minutes: int, step_seconds: int, end: float | None = None
) -> list[dict[str, Any]]:
    """Range query -> [{"metric": {...}, "values": [[ts, "v"], ...]}, ...].

    The window is the `minutes` before `end` (unix seconds, default now)."""
    end = time.time() if end is None else end
    data = await _get(
        "/api/v1/query_range",
        {"query": promql, "start": end - minutes * 60, "end": end, "step": step_seconds},
    )
    return list(data.get("result") or [])


__all__ = ["PrometheusError", "query", "query_range"]
