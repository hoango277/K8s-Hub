"""Điểm vào duy nhất để lấy model AI.

Mọi chỗ trong hệ thống gọi `get_llm()` — KHÔNG import trực tiếp ChatGroq,
ChatGoogleGenerativeAI hay ChatAnthropic. Nhờ vậy đổi nhà cung cấp chỉ cần
sửa LLM_PROVIDER trong .env, không đụng vào code.

    from app.integrations.llm.client import get_llm

    llm = get_llm()                    # model chính, theo cấu hình
    llm = get_llm(profile="fast")      # model rẻ cho việc nhẹ
    llm = get_llm(provider="google")   # ép Gemini cho riêng chỗ này

Trả về `BaseChatModel` của LangChain nên dùng được ngay với LangGraph:

    llm.bind_tools(tools)
    llm.with_structured_output(ActionSpec)
    graph.astream_events(...)

Bộ nhớ đệm model tự xoá mỗi khi cấu hình nạp lại (xem `on_reload` bên dưới),
nên sửa .env rồi là lần gọi sau đã dùng cấu hình mới.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings, on_reload, settings_version
from app.integrations.llm.provider import LLMConfigError, create_chat_model

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


# Nhớ sẵn model đã dựng — tránh tạo lại client HTTP mỗi request.
# Dùng dict thay vì lru_cache để truyền được cả object Settings xuống
# `create_chat_model`; nếu không, provider.py sẽ tự đọc lại cấu hình toàn cục
# và giá trị có thể lệch với cái vừa dùng để tính khoá đệm.
_ModelKey = tuple[str, str, str | None, float | None, int | None, int]
_model_cache: dict[_ModelKey, BaseChatModel] = {}
_cache_lock = threading.Lock()


@on_reload
def _clear_model_cache() -> None:
    """Cấu hình đổi thì model đang nhớ sẵn cũng phải bỏ đi."""
    with _cache_lock:
        _model_cache.clear()


def cache_size() -> int:
    """Số model đang nhớ sẵn. Dùng cho test và endpoint chẩn đoán."""
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
    """Lấy model AI đang được cấu hình.

    Args:
        provider: Ép một nhà cung cấp cụ thể. Bỏ trống thì lấy LLM_PROVIDER.
        profile:  'default' hoặc 'fast'. Dùng 'fast' cho việc nhẹ như phân loại
                  ý định để đỡ tốn tiền.
        model:    Ép một tên model cụ thể, bỏ qua hồ sơ.
        overrides: Tham số truyền thẳng vào constructor (không được nhớ sẵn).
    """
    config = get_settings()

    if overrides:
        # Có tham số riêng thì bỏ qua bộ nhớ đệm.
        return create_chat_model(
            provider,
            config=config,
            profile=profile,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            **overrides,
        )

    name = provider or config.LLM_PROVIDER
    key: _ModelKey = (name, profile, model, temperature, max_tokens, settings_version())

    with _cache_lock:
        cached = _model_cache.get(key)
    if cached is not None:
        return cached

    # Dựng ngoài khoá để không giữ khoá suốt lúc khởi tạo client HTTP.
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
    """Chặn sớm nếu nhà cung cấp không hỗ trợ gọi công cụ.

    CHƯA ĐƯỢC GỌI. Dự định gọi lúc khởi động để lỗi hiện ra ngay, thay vì đến
    khi người dùng chat mới vỡ.
    """
    config = get_settings()
    name = provider or config.LLM_PROVIDER
    spec = config.llm_provider(name)
    if not spec.supports_tool_calling:
        raise LLMConfigError(
            f"Nhà cung cấp {name!r} (model {spec.model}) không hỗ trợ gọi công cụ — "
            f"trợ lý sẽ không tra cứu được gì. Đổi LLM_PROVIDER hoặc đổi sang model có hỗ trợ."
        )


def describe_config(
    *, provider: str | None = None, model: str | None = None
) -> dict[str, Any]:
    """Tóm tắt cấu hình LLM — dùng cho log khởi động và cho công cụ tự khai báo.

    Args:
        provider: Nhà cung cấp thật sự đang chạy cho lượt này. Bỏ trống thì lấy
            cấu hình chung.
        model: Model thật sự đang chạy cho lượt này.

    Hai tham số trên tồn tại vì người dùng chọn được nhà cung cấp và model cho
    RIÊNG một lượt chat. Không truyền vào thì hàm này mô tả cấu hình chung, và
    trợ lý sẽ tự khai sai về chính nó ngay sau khi người dùng đổi model.

    KHÔNG chứa khoá API.
    """
    config = get_settings()
    name = provider or config.LLM_PROVIDER
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
