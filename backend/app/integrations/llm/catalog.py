"""List models straight from the provider.

Why not hard-code the list: providers retire models and release new ones all
the time. A hard-coded list goes stale within months, and the problem only
shows when a user picks a model that has been removed.

Each provider returns a different shape and authenticates differently. That
difference lives entirely in `_PARSERS` below; adding a provider only needs
`models_url` and `models_style` in its spec.

MODEL FILTERING — read this carefully:

The raw list also contains models that cannot chat. Groq returns
`whisper-large-v3` (speech recognition), `orpheus-*` (text to speech) and
`llama-prompt-guard-*` (content classifiers). Showing all of them lets users
pick the wrong one, and the error only appears after they send a question.

Filtering is based on the DATA fields the provider returns, not model names:
filtering by name is a stopgap that breaks as soon as a new model ships.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import ProviderConfig, get_settings, on_reload

logger = logging.getLogger(__name__)

# The model list rarely changes during a session. Asking the provider on every
# page load is slow and wastes quota.
CACHE_TTL_SECONDS = 600

REQUEST_TIMEOUT = 15.0

# Minimum context window for a model to count as chat-capable.
#
# This is a HEURISTIC, and it exists for a specific reason: classifiers like
# llama-prompt-guard have a 512-token window, while our system prompt plus tool
# descriptions alone is almost 700 tokens. They cannot be used for chat even
# though they are text-in/text-out, so modality filtering does not catch them.
MIN_CONTEXT_WINDOW = 2048


class ModelInfo(BaseModel):
    """One model usable in the chat."""

    id: str = Field(description="Name passed to the API, e.g. 'openai/gpt-oss-120b'")
    label: str = Field(description="Display name")
    context_window: int | None = None
    owned_by: str | None = None


class ModelCatalog(BaseModel):
    """Result of listing one provider's models."""

    provider: str
    models: list[ModelInfo]
    source: str = Field(description="'api' = from the provider, 'config' = from the provider spec")
    error: str | None = Field(
        default=None,
        description="Why the API could not be used. When set, source='config'.",
    )


# --------------------------------------------------------------------------
# Parsers, one per response shape
# --------------------------------------------------------------------------


def _parse_openai(data: dict[str, Any]) -> list[ModelInfo]:
    """Groq and every OpenAI-compatible API.

    Filters by modality: drops audio-input models (whisper) and audio-output
    models (orpheus). Then filters by context window to drop classifiers.
    """
    out: list[ModelInfo] = []
    for m in data.get("data") or []:
        if not isinstance(m, dict) or m.get("active") is False:
            continue

        inputs = m.get("input_modalities")
        outputs = m.get("output_modalities")
        # No modality declared: let it through — assume a normal text model.
        if isinstance(inputs, list) and "text" not in inputs:
            continue
        if isinstance(outputs, list) and "text" not in outputs:
            continue

        ctx = m.get("context_window") or m.get("context_length")
        if isinstance(ctx, int) and ctx < MIN_CONTEXT_WINDOW:
            continue

        model_id = m.get("id")
        if not model_id:
            continue
        out.append(
            ModelInfo(
                id=str(model_id),
                label=str(m.get("name") or model_id),
                context_window=ctx if isinstance(ctx, int) else None,
                owned_by=m.get("owned_by"),
            )
        )
    return out


# Google has NO field saying what a model produces.
#
# Groq declares `output_modalities`, so it can be filtered properly. On Google,
# image models (Nano Banana), text to speech (TTS), music (Lyria) and chat
# models all declare the same thing: `generateContent`. Checked directly
# against the API — no `outputModalities`, no `supportedActions`, nothing else.
#
# So this one has to filter by NAME. It is a stopgap with a known limit: if
# Google ships a new model family with an unusual name, it will slip into the
# list. Letting it slip is better than hiding it — a user ignores an odd entry,
# but a usable model that is hidden cannot be picked at all.
GOOGLE_NON_CHAT_MARKERS = (
    "-image",        # image generation
    "nano-banana",   # image generation (brand name)
    "tts",           # text to speech
    "lyria",         # music generation
    "transcribe",    # speech to text
    "embedding",     # embedding vectors
    "imagen",
    "veo",           # video generation
)


def _parse_google(data: dict[str, Any]) -> list[ModelInfo]:
    """Google Gemini.

    Names come back as 'models/gemini-2.5-flash' but calls need the 'models/'
    prefix removed. Only models with 'generateContent' are kept, then models
    that do not produce text are dropped (see GOOGLE_NON_CHAT_MARKERS above).
    """
    out: list[ModelInfo] = []
    for m in data.get("models") or []:
        if not isinstance(m, dict):
            continue
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue

        name = str(m.get("name") or "")
        model_id = name.removeprefix("models/")
        if not model_id:
            continue
        if any(marker in model_id.lower() for marker in GOOGLE_NON_CHAT_MARKERS):
            continue
        out.append(
            ModelInfo(
                id=model_id,
                label=str(m.get("displayName") or model_id),
                context_window=m.get("inputTokenLimit"),
                owned_by="Google",
            )
        )
    return out


_PARSERS = {
    "openai": _parse_openai,
    "google": _parse_google,
}


def _build_request(spec: ProviderConfig, api_key: str) -> tuple[dict, dict]:
    """Return (headers, params) with the provider's auth scheme."""
    if spec.models_style == "google":
        # Google takes the key as a query param, not a header.
        return {}, {"key": api_key, "pageSize": 200}

    return {"Authorization": f"Bearer {api_key}"}, {}


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, ModelCatalog]] = {}


@on_reload
def clear_cache() -> None:
    """A configuration change (usually a new API key) makes the old list stale."""
    _cache.clear()


def _from_spec(provider: str, spec: ProviderConfig, reason: str | None) -> ModelCatalog:
    """Fallback: use the models declared in the provider spec.

    There is always something to pick, even when the network is down or no API
    key is set.
    """
    fallback: list[ModelInfo] = []
    for model_id in (spec.model, spec.fast_model):
        if model_id and all(m.id != model_id for m in fallback):
            fallback.append(ModelInfo(id=model_id, label=model_id))
    return ModelCatalog(
        provider=provider, models=fallback, source="config", error=reason
    )


async def list_models(provider: str | None = None, *, refresh: bool = False) -> ModelCatalog:
    """The usable models of one provider.

    NEVER raises when the provider fails. The model picker is not worth
    breaking the whole page for: it returns the declared models plus the
    reason, and the user can still chat.
    """
    config = get_settings()
    name = provider or config.llm_default_provider()
    spec = config.llm_provider(name)

    if not refresh:
        cached = _cache.get(name)
        if cached and (time.monotonic() - cached[0]) < CACHE_TTL_SECONDS:
            return cached[1]

    if not spec.models_url:
        return _from_spec(name, spec, "This provider has no model listing API configured")

    api_key = str(getattr(config, spec.api_key_field, "") or "").strip()
    if not api_key:
        return _from_spec(name, spec, f"{spec.api_key_field} is not set")

    headers, params = _build_request(spec, api_key)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(spec.models_url, headers=headers, params=params)

        if resp.status_code != 200:
            # Never pass the raw error body on: some providers echo the API key
            # back in their error messages.
            return _from_spec(
                name, spec, f"The provider returned error {resp.status_code}"
            )

        parse = _PARSERS.get(spec.models_style, _parse_openai)
        models = parse(resp.json())

    except Exception as exc:
        logger.warning("Could not list models for %s: %s", name, exc)
        return _from_spec(name, spec, f"Could not reach the API: {type(exc).__name__}")

    if not models:
        return _from_spec(name, spec, "The provider returned no usable models")

    # Do NOT insert the default model when the provider no longer lists it: it
    # has been removed, and inserting it would let the user pick something that
    # fails when called. The frontend falls back to the first model instead.
    models.sort(key=lambda m: m.label.lower())
    result = ModelCatalog(provider=name, models=models, source="api")
    _cache[name] = (time.monotonic(), result)
    return result


__all__ = [
    "CACHE_TTL_SECONDS",
    "MIN_CONTEXT_WINDOW",
    "ModelCatalog",
    "ModelInfo",
    "clear_cache",
    "list_models",
]
