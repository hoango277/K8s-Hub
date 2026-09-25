"""Tests for reading the model list from providers.

The sample data below comes from REAL API responses (Groq called directly;
Google per their documentation). Keeping that exact shape is deliberate: if a
provider changes its response structure this test must go red, rather than
letting the UI silently show an empty picker.
"""

from __future__ import annotations

from app.integrations.llm.catalog import (
    GOOGLE_NON_CHAT_MARKERS,
    MIN_CONTEXT_WINDOW,
    _parse_google,
    _parse_openai,
)

# Trimmed from a real response of https://api.groq.com/openai/v1/models
GROQ_REAL = {
    "object": "list",
    "data": [
        {
            "id": "openai/gpt-oss-120b",
            "name": "GPT OSS 120B",
            "owned_by": "OpenAI",
            "active": True,
            "context_window": 131072,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            # Speech recognition — can't chat.
            "id": "whisper-large-v3",
            "name": "Whisper Large v3",
            "owned_by": "OpenAI",
            "active": True,
            "context_window": 448,
            "input_modalities": ["audio"],
            "output_modalities": ["transcription"],
        },
        {
            # Text-to-speech — takes text but emits audio.
            "id": "canopylabs/orpheus-v1-english",
            "name": "Orpheus",
            "owned_by": "Canopy Labs",
            "active": True,
            "context_window": 4000,
            "input_modalities": ["text"],
            "output_modalities": ["speech"],
        },
        {
            # Content classifier: text in, text out, but only a 512 window.
            "id": "meta-llama/llama-prompt-guard-2-86m",
            "name": "Llama Prompt Guard 2 86M",
            "owned_by": "Meta",
            "active": True,
            "context_window": 512,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "qwen/qwen3.6-27b",
            "name": "Qwen3.6 27B",
            "owned_by": "Alibaba Cloud",
            "active": True,
            "context_window": 131072,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
    ],
}


def ids(models) -> list[str]:
    return [m.id for m in models]


# --------------------------------------------------------------------------
# Groq / OpenAI-compatible APIs
# --------------------------------------------------------------------------


def test_drops_audio_input_models():
    """Whisper takes audio; putting it in the picker invites a wrong choice."""
    assert "whisper-large-v3" not in ids(_parse_openai(GROQ_REAL))


def test_drops_audio_output_models():
    """Orpheus takes text but emits speech — filtered by output_modalities."""
    assert "canopylabs/orpheus-v1-english" not in ids(_parse_openai(GROQ_REAL))


def test_drops_classifier_with_too_small_window():
    """prompt-guard is text in - text out, so modality can't filter it.

    It is dropped because of its 512-token window, too small to even hold the
    system prompt.
    """
    assert "meta-llama/llama-prompt-guard-2-86m" not in ids(_parse_openai(GROQ_REAL))


def test_keeps_chat_models():
    result = ids(_parse_openai(GROQ_REAL))
    assert "openai/gpt-oss-120b" in result
    # A model that also accepts images is still a chat model and must not be dropped.
    assert "qwen/qwen3.6-27b" in result


def test_reads_display_name_and_window():
    m = next(m for m in _parse_openai(GROQ_REAL) if m.id == "openai/gpt-oss-120b")
    assert m.label == "GPT OSS 120B"
    assert m.context_window == 131072
    assert m.owned_by == "OpenAI"


def test_drops_inactive_models():
    data = {"data": [{**GROQ_REAL["data"][0], "active": False}]}
    assert _parse_openai(data) == []


def test_keeps_models_without_modality_fields():
    """Other OpenAI-compatible APIs may not declare modalities.

    Missing information means let it through, don't wipe out their whole list.
    """
    data = {"data": [{"id": "some-model", "context_window": 8192}]}
    assert ids(_parse_openai(data)) == ["some-model"]


def test_window_threshold_uses_shared_constant():
    """Guards against 'changed the constant but forgot the filter'."""
    data = {
        "data": [
            {"id": "just-enough", "context_window": MIN_CONTEXT_WINDOW},
            {"id": "one-short", "context_window": MIN_CONTEXT_WINDOW - 1},
        ]
    }
    assert ids(_parse_openai(data)) == ["just-enough"]


def test_malformed_data_does_not_crash():
    assert _parse_openai({}) == []
    assert _parse_openai({"data": [None, "string", 123]}) == []
    assert _parse_openai({"data": [{"no_id": 1}]}) == []


# --------------------------------------------------------------------------
# Google Gemini
# --------------------------------------------------------------------------

GOOGLE_SAMPLE = {
    "models": [
        {
            "name": "models/gemini-2.5-flash",
            "displayName": "Gemini 2.5 Flash",
            "inputTokenLimit": 1048576,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            # Embedding model — can't chat.
            "name": "models/text-embedding-004",
            "displayName": "Text Embedding 004",
            "inputTokenLimit": 2048,
            "supportedGenerationMethods": ["embedContent"],
        },
    ]
}


def test_google_strips_models_prefix():
    """Names come back as 'models/gemini-...' but the prefix must be dropped when calling.

    Otherwise every call fails with a 404 on the provider side.
    """
    assert ids(_parse_google(GOOGLE_SAMPLE)) == ["gemini-2.5-flash"]


def test_google_drops_non_generating_models():
    assert "text-embedding-004" not in ids(_parse_google(GOOGLE_SAMPLE))


def test_google_uses_token_limit_as_window():
    m = _parse_google(GOOGLE_SAMPLE)[0]
    assert m.label == "Gemini 2.5 Flash"
    assert m.context_window == 1048576


def test_google_malformed_data():
    assert _parse_google({}) == []
    assert _parse_google({"models": [{"name": "models/"}]}) == []


def test_google_drops_models_that_dont_produce_text():
    """Google declares EVERYTHING as 'generateContent', including image
    generation and text-to-speech models. The list below uses REAL ids from the API."""
    data = {
        "models": [
            {"name": f"models/{model_id}", "supportedGenerationMethods": ["generateContent"]}
            for model_id in (
                "gemini-2.5-flash",
                "gemini-2.5-flash-image",        # Nano Banana, image generation
                "nano-banana-pro-preview",       # image generation
                "gemini-2.5-flash-preview-tts",  # text-to-speech
                "gemini-3.1-flash-tts-preview",
                "lyria-3.5",                     # music generation
                "gemini-3.5-transcribe",         # speech recognition
                "gemini-3.5-flash",
            )
        ]
    }
    assert ids(_parse_google(data)) == ["gemini-2.5-flash", "gemini-3.5-flash"]


def test_google_does_not_over_filter():
    """Chat models with unusual names must still be kept.

    Hiding a usable model leaves the user no way to pick it.
    """
    data = {
        "models": [
            {"name": f"models/{model_id}", "supportedGenerationMethods": ["generateContent"]}
            for model_id in (
                "gemma-4-31b-it",
                "deep-research-pro-preview-12-2025",
                "gemini-2.5-computer-use-preview-10-2025",
            )
        ]
    }
    assert len(_parse_google(data)) == 3


def test_exclusion_list_is_not_empty():
    """Guards against accidentally wiping out the exclusion list."""
    assert len(GOOGLE_NON_CHAT_MARKERS) >= 5
