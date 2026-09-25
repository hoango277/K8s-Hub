"""The single entry point for getting an AI model.

Everything in the system calls `get_llm()` — do NOT import ChatGroq or
ChatGoogleGenerativeAI directly. The provider and model are chosen per chat
turn; if left empty, the first provider that has an API key is used.

    from app.integrations.llm.client import get_llm

    llm = get_llm()                    # main model, per configuration
    llm = get_llm(profile="fast")      # cheap model for light work
    llm = get_llm(provider="google")   # force Gemini just for this spot

It returns a LangChain `BaseChatModel`, so it works with LangGraph right away:

    llm.bind_tools(tools)
    llm.with_structured_output(ActionSpec)
    graph.astream_events(...)

The model cache clears itself whenever the configuration reloads (see
`on_reload` below), so after editing .env the next call already uses the new
configuration.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings, on_reload, settings_version
from app.integrations.llm.provider import LLMConfigError, create_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


# Keep built models around — avoids recreating the HTTP client on every request.
# A dict is used instead of lru_cache so the Settings object itself can be
# passed down to `create_chat_model`; otherwise provider.py would re-read the
# global configuration and its values could drift from the ones just used to
# compute the cache key.
_ModelKey = tuple[str, str, str | None, float | None, int | None, int]
_model_cache: dict[_ModelKey, BaseChatModel] = {}
_cache_lock = threading.Lock()


@on_reload
def _clear_model_cache() -> None:
    """When the configuration changes, cached models must be dropped too."""
    with _cache_lock:
        _model_cache.clear()


def cache_size() -> int:
    """Number of cached models. Used by tests and the diagnostics endpoint."""
    with _cache_lock:
        return len(_model_cache)


def get_llm(
    *,
    provider: str | None = None,
    profile: str = "default",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    **overrides: Any,
) -> BaseChatModel:
    """Get the currently configured AI model.

    Args:
        provider: Force a specific provider. If empty, the first provider that
                  has an API key is used (`Settings.llm_default_provider`).
        profile:  'default' or 'fast'. Use 'fast' for light work such as intent
                  classification to save money.
        model:    Force a specific model name, ignoring the profile.
        overrides: Parameters passed straight to the constructor (not cached).
    """
    config = get_settings()

    if overrides:
        # Custom parameters bypass the cache.
        return create_chat_model(
            provider,
            config=config,
            profile=profile,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **overrides,
        )

    name = provider or config.llm_default_provider()
    key: _ModelKey = (name, profile, model, temperature, max_tokens, settings_version())

    with _cache_lock:
        cached = _model_cache.get(key)
    if cached is not None:
        return cached

    # Build outside the lock so it isn't held while the HTTP client initializes.
    built = create_chat_model(
        name,
        config=config,
        profile=profile,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    with _cache_lock:
        return _model_cache.setdefault(key, built)


def require_tool_calling(provider: str | None = None) -> None:
    """Fail early if the provider doesn't support tool calling.

    NOT CALLED YET. Intended to be called at startup so the error shows up
    immediately, instead of breaking only when a user starts chatting.
    """
    config = get_settings()
    name = provider or config.llm_default_provider()
    spec = config.llm_provider(name)
    if not spec.supports_tool_calling:
        raise LLMConfigError(
            f"Provider {name!r} (model {spec.model}) does not support tool calling — "
            f"the assistant won't be able to look anything up. Pick another provider or model."
        )


def describe_config(
    *, provider: str | None = None, model: str | None = None
) -> dict[str, Any]:
    """Summarize the LLM configuration — for the startup log and the self-describing tool.

    Args:
        provider: The provider actually running for this turn. If empty, the
            global configuration is used.
        model: The model actually running for this turn.

    These two parameters exist because users can pick the provider and model
    for a SINGLE chat turn. Without them this function describes the global
    configuration, and the assistant would misreport itself right after the
    user switched models.

    Does NOT contain API keys.
    """
    config = get_settings()
    name = provider or config.llm_default_provider()
    spec = config.llm_provider(name)
    return {
        "provider": name,
        "model": model or config.llm_model_name(provider=name, profile="default"),
        "fast_model": config.llm_model_name(provider=name, profile="fast"),
        "temperature": config.LLM_TEMPERATURE,
        "max_tokens": config.LLM_MAX_TOKENS,
        "timeout_seconds": config.LLM_TIMEOUT_SECONDS,
        "max_retries": config.LLM_MAX_RETRIES,
        "tool_calling": spec.supports_tool_calling,
        "streaming": spec.supports_streaming,
        "structured_output": spec.supports_structured_output,
        "api_key_set": bool(getattr(config, spec.api_key_field, "")),
        "available_providers": sorted(config.LLM_PROVIDERS),
    }


__all__ = [
    "describe_config",
    "get_llm",
    "require_tool_calling",
]
