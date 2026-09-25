"""Logging setup: everything goes to stdout, nothing is pushed anywhere.

Before this module existed nothing configured the root logger, so every
`logger.info(...)` under `app.*` was silently dropped (Python's default root
level is WARNING) — including "Langfuse enabled" / "Langfuse is disabled",
which is exactly the line you want when tracing doesn't show up.

WHY ONLY STDOUT, never a handler that pushes to Loki: on the cluster, Alloy
(`loki.source.kubernetes.pods`) already reads the stdout of EVERY pod and ships
it to Loki with namespace/pod/container labels. Pushing from the app instead
would lose buffered lines when the pod crashes (exactly when you need them),
drop lines while Loki is down, miss those Kubernetes labels, tie the app to
Loki's address, and duplicate every line alongside Alloy.

LOG_FORMAT:
  - text (default): readable lines for a developer's console.
  - json: one JSON object per line, for running as a pod — Grafana's `| json`
    parser can then filter on any field without regexes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings

_TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Access-log lines for these paths are noise: Prometheus hits /metrics every
# scrape interval and health probes are just as regular.
_QUIET_PATHS = ('"GET /metrics', '"GET /api/v1/health')


class _QuietAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not any(path in message for path in _QUIET_PATHS)


class JsonFormatter(logging.Formatter):
    """One JSON object per line. No timestamp field: the container runtime
    stamps every stdout line, and Alloy uses that as the Loki timestamp."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        # Anything passed as `logger.info(..., extra={"trace_id": ...})`.
        for key in ("trace_id", "thread_id", "user"):
            value = getattr(record, key, None)
            if value is not None:
                data[key] = str(value)
        return json.dumps(data, ensure_ascii=False)


_configured = False


def setup_logging() -> None:
    """Configure logging once. Safe to call again (does nothing)."""
    global _configured
    if _configured:
        return
    _configured = True

    config = get_settings()
    formatter: logging.Formatter = (
        JsonFormatter() if config.LOG_FORMAT == "json" else logging.Formatter(_TEXT_FORMAT)
    )

    # Root stays at INFO even with DEBUG=true: DEBUG on the root turns on every
    # library's debug output — sse-starlette alone logs one line per streamed
    # token. DEBUG only raises OUR loggers (app.*).
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    logging.getLogger("app").setLevel(logging.DEBUG if config.DEBUG else logging.INFO)

    # SQL statements only on a developer machine (DEBUG and APP_ENV=local).
    # Never elsewhere: the logged parameters include message content and the
    # assistant's reasoning — user data that must not end up in Loki.
    if config.DEBUG and config.APP_ENV == "local":
        logging.getLogger("sqlalchemy.engine").setLevel(logging.INFO)

    # Third-party chatter that drowns out our own lines at INFO.
    for noisy in ("httpx", "httpcore", "urllib3", "openai", "groq", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # uvicorn's loggers don't propagate to root and have their own handlers.
    # In json mode give them the same format, otherwise a pod's stdout mixes
    # JSON and plain lines and `| json` fails on half of them.
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        for handler in logging.getLogger(name).handlers:
            if config.LOG_FORMAT == "json":
                handler.setFormatter(formatter)
    logging.getLogger("uvicorn.access").addFilter(_QuietAccessFilter())


__all__ = ["JsonFormatter", "setup_logging"]
