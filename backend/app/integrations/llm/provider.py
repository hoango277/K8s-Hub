"""Build LLM models from the specs in `app.core.config`.

This module does NOT read environment variables or any configuration file.
Every value comes through `Settings` — following the flow .env -> config.py -> here.

Its only job: dynamically import the right class and rename the system's
canonical parameter names to each provider's real names (see
`ProviderConfig.param_map`).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from app.core.config import CANONICAL_LLM_PARAMS, ProviderConfig, Settings, get_settings

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


class LLMConfigError(RuntimeError):
    """Invalid LLM configuration: no provider, missing key, wrong name mapping..."""


class LLMProviderNotInstalledError(LLMConfigError):
    """The provider's Python package isn't installed."""


def import_chat_class(spec: ProviderConfig) -> type:
    """Import the provider's class. Reports an error with the install command if missing."""
    try:
        module = importlib.import_module(spec.module)
    except ImportError as exc:
        raise LLMProviderNotInstalledError(
            f"The package for this provider is not installed. Run:  pip install {spec.package}"
        ) from exc

    try:
        return getattr(module, spec.class_name)
    except AttributeError as exc:
        raise LLMConfigError(
            f"Module {spec.module!r} has no class {spec.class_name!r}. "
            f"Check 'class_name' in LLM_PROVIDERS."
        ) from exc


def _first(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def build_params(
    config: Settings,
    provider: str,
    *,
    profile: str = "default",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Merge values, then rename them to the provider's real parameter names.

    Explicitly passed parameters win over values in Settings. Parameters the
    provider doesn't declare in `param_map` are skipped and not passed to the
    constructor.
    """
    spec = config.llm_provider(provider)

    canonical: dict[str, Any] = {
        "api_key": config.llm_api_key(provider=provider),
        "model": model or config.llm_model_name(provider=provider, profile=profile),
        "temperature": _first(temperature, config.LLM_TEMPERATURE),
        "max_tokens": _first(max_tokens, config.LLM_MAX_TOKENS),
        "timeout": _first(timeout, config.LLM_TIMEOUT_SECONDS),
        "max_retries": _first(max_retries, config.LLM_MAX_RETRIES),
    }

    unknown = set(spec.param_map) - set(CANONICAL_LLM_PARAMS)
    if unknown:
        raise LLMConfigError(
            f"Provider {provider!r}: param_map has unknown keys {sorted(unknown)}. "
            f"Only {', '.join(CANONICAL_LLM_PARAMS)} are accepted. "
            f"Put provider-specific parameters in 'extra'."
        )

    kwargs: dict[str, Any] = {}
    for canon_name, value in canonical.items():
        if value is None:
            continue
        real_name = spec.param_map.get(canon_name)
        if real_name is None:
            continue  # the provider doesn't accept this parameter
        kwargs[real_name] = value

    kwargs.update(spec.extra)
    return kwargs


def create_chat_model(
    provider: str | None = None,
    *,
    config: Settings | None = None,
    profile: str = "default",
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    max_retries: int | None = None,
    **overrides: Any,
) -> BaseChatModel:
    """Build a LangChain `BaseChatModel`, ready to use with LangGraph."""
    cfg = config or get_settings()
    name = provider or cfg.llm_default_provider()

    try:
        spec = cfg.llm_provider(name)
    except ValueError as exc:
        raise LLMConfigError(str(exc)) from exc

    try:
        kwargs = build_params(
            cfg,
            name,
            profile=profile,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
        )
    except ValueError as exc:  # missing API key
        raise LLMConfigError(str(exc)) from exc

    kwargs.update(overrides)
    cls = import_chat_class(spec)

    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise LLMConfigError(
            f"Could not build {spec.class_name} for provider {name!r}. "
            f"'param_map' may map to the wrong parameter names. "
            f"Passed: {sorted(kwargs)}. Original error: {exc}"
        ) from exc


__all__ = [
    "LLMConfigError",
    "LLMProviderNotInstalledError",
    "build_params",
    "create_chat_model",
    "import_chat_class",
]
