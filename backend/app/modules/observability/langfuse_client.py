"""Initialize Langfuse and the system-wide shared `TracerProvider`.

THE MOST IMPORTANT THING TO KNOW: from version 3 on, Langfuse **is
OpenTelemetry**, not a parallel system. Specifically, the SDK:

  - accepts an existing `TracerProvider` (the `tracer_provider` parameter),
  - attaches its own `SpanProcessor` to that provider,
  - and takes the `trace_id` from OTel's own span context.

So "OTel or Langfuse?" is the wrong question. We build ONE single provider
here, and Langfuse plugs into it. Later, instrumentation for FastAPI or
SQLAlchemy plugs into the same provider, and everything lands in one trace:
HTTP request -> DB query -> model call -> each tool call.

No need to worry about noise: Langfuse's default filter
(`is_default_export_span`) only exports spans it created itself, spans with
`gen_ai.*` attributes, or spans from known LLM libraries. HTTP and DB spans are
skipped.

With Langfuse disabled, every function here returns None and callers keep
running normally — missing observability must NEVER break the chat flow.

CONFIGURATION IS READ ONCE AT STARTUP. Unlike `LLM_TEMPERATURE` or
`LLM_MAX_TOKENS`, the `LANGFUSE_*` fields deliberately CANNOT be edited in the
web UI, because inside the SDK `LangfuseResourceManager` is a singleton keyed by
public key:

    if public_key in cls._instances:
        return cls._instances[public_key]

Rebuilding the client with the same public key but a different host makes the
SDK return the old object and silently ignore the new host — the user would
keep editing without understanding why no traces show up. Better to say
plainly that it must be changed in `.env` followed by a restart.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings

if TYPE_CHECKING:
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_provider: TracerProvider | None = None
_client: Langfuse | None = None
_init_attempted = False


# ---------------------------------------------------------------------------
# Shared TracerProvider
# ---------------------------------------------------------------------------


def get_tracer_provider() -> TracerProvider:
    """The system-wide shared provider. Built once, reused forever."""
    global _provider
    if _provider is not None:
        return _provider

    from opentelemetry import trace as otel_trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider

    with _lock:
        if _provider is not None:
            return _provider

        config = get_settings()
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": "k8s-hub-backend",
                    "service.version": "0.1.0",
                    "deployment.environment": config.APP_ENV,
                }
            )
        )

        # Set it as the global provider so other libraries (FastAPI,
        # SQLAlchemy instrumentation...) find it without passing it by hand.
        #
        # OTel only allows setting it ONCE: the second attempt is ignored and
        # just logged. So check first, otherwise every config reload would
        # produce a pointless warning.
        current = otel_trace.get_tracer_provider()
        if isinstance(current, otel_trace.ProxyTracerProvider):
            otel_trace.set_tracer_provider(provider)
        else:
            logger.debug("A global TracerProvider already exists, not overriding it")

        _provider = provider
        return provider


# ---------------------------------------------------------------------------
# Langfuse client
# ---------------------------------------------------------------------------


def init_langfuse() -> Langfuse | None:
    """Build the Langfuse client from configuration. Returns None if disabled or keys are missing.

    No network calls — it only builds the object. Connection checking lives
    separately in `check_langfuse()` because it is slow and shouldn't block
    startup.
    """
    global _client, _init_attempted

    config = get_settings()

    with _lock:
        _init_attempted = True

        if not config.LANGFUSE_ENABLED:
            logger.info("Langfuse is disabled (LANGFUSE_ENABLED=false)")
            _client = None
            return None

        if not (config.LANGFUSE_PUBLIC_KEY and config.LANGFUSE_SECRET_KEY):
            logger.warning(
                "LANGFUSE_ENABLED=true but keys are missing. Set LANGFUSE_PUBLIC_KEY "
                "and LANGFUSE_SECRET_KEY. Running without observability for now."
            )
            _client = None
            return None

        try:
            from langfuse import Langfuse
        except ImportError:
            logger.warning("The langfuse package is not installed. Run: pip install langfuse")
            _client = None
            return None

    provider = get_tracer_provider()

    try:
        client = Langfuse(
            public_key=config.LANGFUSE_PUBLIC_KEY,
            secret_key=config.LANGFUSE_SECRET_KEY,
            host=config.LANGFUSE_HOST,
            environment=config.APP_ENV,
            release="0.1.0",
            tracer_provider=provider,
        )
    except Exception:
        # A bad Langfuse configuration must NOT crash the app: better to lose
        # observability than to lose the chat panel altogether.
        logger.exception("Could not build the Langfuse client, continuing without observability")
        with _lock:
            _client = None
        return None

    with _lock:
        _client = client
    logger.info(
        "Langfuse enabled at %s (environment: %s)", config.LANGFUSE_HOST, config.APP_ENV
    )
    return client


def get_langfuse() -> Langfuse | None:
    """The client in use, or None when disabled. Initializes itself on first call."""
    if not _init_attempted:
        return init_langfuse()
    return _client


async def check_langfuse() -> dict[str, Any]:
    """Try authenticating with the Langfuse server. Used at startup and for health checks.

    Runs in a separate thread because the SDK's `auth_check()` is a synchronous
    function that makes a network call — calling it directly on the event loop
    would block every other request.
    """
    client = get_langfuse()
    if client is None:
        return {"enabled": False}

    try:
        ok = await asyncio.to_thread(client.auth_check)
    except Exception as exc:
        return {"enabled": True, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"enabled": True, "ok": bool(ok)}


def get_callback_handler(*, trace_id: str | None = None) -> Any | None:
    """Handler that lets LangGraph report its progress to Langfuse.

    Args:
        trace_id: Force the trace id for this turn. SHOULD always be passed,
            because the system writes `trace_id` to the `messages` table BEFORE
            the graph runs — without forcing it, Langfuse generates a different
            id and the two sides can't be joined
            (see `app/modules/observability/impact.py`).

    Returns None when Langfuse is disabled; the caller simply passes no callback.
    """
    if get_langfuse() is None:
        return None

    try:
        from langfuse.langchain import CallbackHandler
    except ImportError:
        logger.warning("Could not import langfuse.langchain.CallbackHandler")
        return None

    try:
        if trace_id:
            return CallbackHandler(trace_context={"trace_id": trace_id})
        return CallbackHandler()
    except Exception:
        logger.exception("Could not build the Langfuse CallbackHandler")
        return None


def shutdown_langfuse() -> None:
    """Flush whatever is left in the queue, then close. Called at app shutdown.

    Skipping this loses the traces from the last few seconds — the SDK batches
    them instead of sending each one immediately.
    """
    global _client
    with _lock:
        client = _client
        _client = None
    if client is None:
        return
    try:
        client.flush()
        client.shutdown()
        logger.info("Langfuse closed")
    except Exception:
        logger.exception("Error while closing Langfuse")


__all__ = [
    "check_langfuse",
    "get_callback_handler",
    "get_langfuse",
    "get_tracer_provider",
    "init_langfuse",
    "shutdown_langfuse",
]
