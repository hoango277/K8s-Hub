"""Dựng model LLM từ đặc tả trong `app.core.config`.

Module này KHÔNG đọc biến môi trường, KHÔNG đọc file cấu hình nào.
Mọi giá trị đều lấy qua `Settings` — đúng luồng  .env -> config.py -> đây.

Việc duy nhất nó làm: import động đúng class và đổi tên tham số chuẩn của hệ
thống sang tên thật của từng nhà cung cấp (xem `ProviderConfig.param_map`).
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from app.core.config import CANONICAL_LLM_PARAMS, ProviderConfig, Settings, get_settings

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel


class LLMConfigError(RuntimeError):
    """Cấu hình LLM sai: không có nhà cung cấp, thiếu khoá, ánh xạ sai tên..."""


class LLMProviderNotInstalled(LLMConfigError):
    """Chưa cài gói Python của nhà cung cấp."""


def import_chat_class(spec: ProviderConfig) -> type:
    """Import class của nhà cung cấp. Báo lỗi kèm lệnh cài nếu thiếu gói."""
    try:
        module = importlib.import_module(spec.module)
    except ImportError as exc:
        raise LLMProviderNotInstalled(
            f"Chưa cài gói cho nhà cung cấp này. Chạy:  uv pip install {spec.package}"
        ) from exc

    try:
        return getattr(module, spec.class_name)
    except AttributeError as exc:
        raise LLMConfigError(
            f"Module {spec.module!r} không có class {spec.class_name!r}. "
            f"Kiểm tra lại 'class_name' trong LLM_PROVIDERS."
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
    """Gộp giá trị rồi đổi sang tên tham số thật của nhà cung cấp.

    Tham số truyền tay thắng giá trị trong Settings. Tham số nào nhà cung cấp
    không khai báo trong `param_map` thì bỏ qua, không truyền vào constructor.
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
            f"Nhà cung cấp {provider!r}: param_map có khoá lạ {sorted(unknown)}. "
            f"Chỉ chấp nhận {', '.join(CANONICAL_LLM_PARAMS)}. "
            f"Tham số riêng thì để trong 'extra'."
        )

    kwargs: dict[str, Any] = {}
    for canon_name, value in canonical.items():
        if value is None:
            continue
        real_name = spec.param_map.get(canon_name)
        if real_name is None:
            continue  # nhà cung cấp không nhận tham số này
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
    """Dựng một `BaseChatModel` của LangChain, dùng được ngay với LangGraph."""
    cfg = config or get_settings()
    name = provider or cfg.LLM_PROVIDER

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
    except ValueError as exc:  # thiếu khoá API
        raise LLMConfigError(str(exc)) from exc

    kwargs.update(overrides)
    cls = import_chat_class(spec)

    try:
        return cls(**kwargs)
    except TypeError as exc:
        raise LLMConfigError(
            f"Không dựng được {spec.class_name} cho nhà cung cấp {name!r}. "
            f"Có thể 'param_map' ánh xạ sai tên tham số. "
            f"Đã truyền: {sorted(kwargs)}. Lỗi gốc: {exc}"
        ) from exc


__all__ = [
    "LLMConfigError",
    "LLMProviderNotInstalled",
    "build_params",
    "create_chat_model",
    "import_chat_class",
]
