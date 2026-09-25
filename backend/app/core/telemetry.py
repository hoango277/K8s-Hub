"""Self-monitoring: Prometheus metrics for the K8s-Hub backend itself.

Entirely different from the following two, even though they share tooling:
  - app/integrations/prometheus, app/integrations/loki
      -> READ the target K8s cluster, as evidence for RCA
  - app/modules/observability
      -> monitor the LLM/agent in detail (Langfuse)

This module WRITES our own numbers for Prometheus to scrape at `/metrics`.
Logs only go to stdout, see `app/core/logging.py`.

ONLY SERVICE HEALTH, NOTHING ABOUT WHAT THE AI DID. Tokens, cost, tool calls,
per-user and per-conversation usage are already in Langfuse, in more detail
(per turn, per step). Copying them here would mean two sources that can
disagree. Prometheus keeps what Langfuse cannot tell you — is the service
healthy right now: open streams, error rate, latency — because that is what
Grafana dashboards and Alertmanager rules are built on.

Label cardinality is deliberately low: provider, model, outcome.
NEVER label by user, thread or trace id — every distinct value becomes a new
time series in Prometheus, and per-user labels grow without bound.
"""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram

# --------------------------------------------------------------------------
# Chat metrics — updated from app/api/v1/chat.py
# --------------------------------------------------------------------------

CHAT_STREAMS_ACTIVE = Gauge(
    "k8shub_chat_streams_active",
    "SSE chat streams currently open. A value that only ever climbs means "
    "streams are leaking (not closed on disconnect).",
)

CHAT_TURNS = Counter(
    "k8shub_chat_turns_total",
    "Finished chat turns, by how they ended.",
    ["provider", "model", "outcome"],  # outcome: ok | error | cancelled
)

CHAT_TURN_SECONDS = Histogram(
    "k8shub_chat_turn_duration_seconds",
    "Wall-clock time of a whole chat turn, including every tool round.",
    ["provider"],
    # LLM turns are slow: default buckets (max 10s) would put most turns in +Inf.
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)

def record_chat_turn(
    *,
    provider: str,
    model: str,
    outcome: str,
    seconds: float,
) -> None:
    """Record one finished turn. Must never raise — metrics can't break chat."""
    try:
        CHAT_TURNS.labels(provider, model, outcome).inc()
        CHAT_TURN_SECONDS.labels(provider).observe(seconds)
    except Exception:  # pragma: no cover - defensive
        pass


# --------------------------------------------------------------------------
# HTTP metrics + the /metrics endpoint
# --------------------------------------------------------------------------

# Not measured as HTTP traffic: Prometheus scraping /metrics every 30s and
# health probes would otherwise dominate the request-rate graphs.
_EXCLUDED = ["/metrics", r"/api/v1/health.*"]


def setup_metrics(app: FastAPI) -> None:
    """Add RED metrics per endpoint and expose `/metrics`.

    Mounted at the app root, not under /api/v1: the Next.js proxy only
    forwards /api/v1, so the browser can't reach it through the frontend —
    only whoever can reach the backend port directly (Prometheus).
    """
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,  # unknown paths would each be a new series
        excluded_handlers=_EXCLUDED,
        # SSE responses stay open for the whole turn; "in progress" shows them.
        should_instrument_requests_inprogress=True,
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


__all__ = [
    "CHAT_STREAMS_ACTIVE",
    "CHAT_TURNS",
    "CHAT_TURN_SECONDS",
    "record_chat_turn",
    "setup_metrics",
]
