"""Cấu hình ứng dụng — nguồn duy nhất cho toàn hệ thống.

Hai tầng chồng lên nhau:

    .env  (CỨNG, đọc một lần lúc khởi động)
      +
    phần người dùng đổi trên giao diện web  (NÓNG, đổi lúc chạy)
      =
    cấu hình đang có hiệu lực  ->  mọi module khác

  - `.env` giữ thứ không đổi lúc chạy: chuỗi kết nối CSDL, khoá JWT, môi trường.
    Sửa file này KHÔNG tự động có hiệu lực — phải gọi `reload_from_env()`.
  - Giao diện web đổi những trường trong `RUNTIME_EDITABLE` qua `apply_overrides()`.
    Giá trị được kiểm tra trước khi áp; sai thì giữ nguyên cấu hình cũ.
  - `config.py` là lớp cấu hình DUY NHẤT. Không module nào được đọc os.environ
    hay file cấu hình riêng — tất cả đi qua đây.

Dùng:

    from app.core.config import settings
    print(settings.LLM_PROVIDER)     # luôn là giá trị mới nhất

Module nào nhớ sẵn thứ dựng từ cấu hình thì đăng ký `on_reload()` để dọn đệm
mỗi khi cấu hình đổi.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from typing import Annotated, Any, Literal, Protocol, get_args, get_origin

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# ---------------------------------------------------------------------------
# Đặc tả nhà cung cấp LLM
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Mọi thứ cần biết để dựng một model của một nhà cung cấp.

    `param_map` là chỗ hấp thụ khác biệt giữa các nhà cung cấp: khoá là tên
    tham số chuẩn của hệ thống, giá trị là tên tham số thật của class đó.
    Ví dụ Gemini gọi `max_tokens` là `max_output_tokens`.
    """

    package: str = Field(description="Tên gói pip, dùng để gợi ý khi chưa cài")
    module: str = Field(description="Đường dẫn import, ví dụ langchain_groq")
    class_name: str = Field(description="Tên class trong module đó")
    api_key_field: str = Field(description="Tên field khoá API trong Settings")

    model: str = Field(description="Model chính")
    fast_model: str = Field(default="", description="Model rẻ cho việc nhẹ")

    param_map: dict[str, str] = Field(
        description="tên chuẩn -> tên thật của nhà cung cấp",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, description="Tham số riêng, truyền thẳng vào constructor"
    )

    supports_tool_calling: bool = True
    supports_streaming: bool = True
    supports_structured_output: bool = True
    notes: str = ""

    # --- Lấy danh sách model trực tiếp từ nhà cung cấp ---
    #
    # Để ở đây thay vì viết cứng trong code: thêm một nhà cung cấp mới chỉ cần
    # khai báo thêm một mục trong LLM_PROVIDERS, không phải sửa file nào.
    models_url: str = Field(
        default="",
        description="Địa chỉ API liệt kê model. Bỏ trống thì chỉ dùng model khai trong cấu hình.",
    )
    models_style: Literal["openai", "google", "anthropic"] = Field(
        default="openai",
        description=(
            "Kiểu trả về và cách xác thực của API liệt kê model. "
            "'openai' (Groq và các API tương thích): Bearer token, kết quả ở khoá 'data'. "
            "'google': khoá API gửi qua query param, kết quả ở khoá 'models'. "
            "'anthropic': header x-api-key, kết quả ở khoá 'data'."
        ),
    )


# Tham số chuẩn của hệ thống. Nhà cung cấp nào không có tham số tương ứng thì
# bỏ khoá đó khỏi param_map, nó sẽ không được truyền vào constructor.
CANONICAL_LLM_PARAMS = (
    "api_key",
    "model",
    "temperature",
    "max_tokens",
    "timeout",
    "max_retries",
)


DEFAULT_LLM_PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        package="langchain-groq",
        module="langchain_groq",
        class_name="ChatGroq",
        api_key_field="GROQ_API_KEY",
        models_url="https://api.groq.com/openai/v1/models",
        models_style="openai",
        model="llama-3.3-70b-versatile",
        fast_model="llama-3.1-8b-instant",
        param_map={
            "api_key": "api_key",
            "model": "model",
            "temperature": "temperature",
            "max_tokens": "max_tokens",
            "timeout": "request_timeout",
            "max_retries": "max_retries",
        },
        notes=(
            "Nhanh và rẻ nhất. Chỉ một số model hỗ trợ gọi công cụ. "
            "Model nhỏ hay bịa tên công cụ, không nên dùng để sinh phiếu lệnh."
        ),
    ),
    "google": ProviderConfig(
        package="langchain-google-genai",
        module="langchain_google_genai",
        class_name="ChatGoogleGenerativeAI",
        api_key_field="GOOGLE_API_KEY",
        models_url="https://generativelanguage.googleapis.com/v1beta/models",
        models_style="google",
        model="gemini-2.5-flash",
        fast_model="gemini-2.5-flash-lite",
        param_map={
            "api_key": "google_api_key",      # khác: không phải api_key
            "model": "model",
            "temperature": "temperature",
            "max_tokens": "max_output_tokens",  # khác: không phải max_tokens
            "timeout": "timeout",
            "max_retries": "max_retries",
        },
        extra={
            # Gemini CÓ suy luận nhưng mặc định không gửi phần đó về, nên khung
            # chat sẽ không hiện được "Đang suy nghĩ". Bật lên để nó trả kèm.
            #
            # Không tốn thêm tiền: token suy luận vẫn bị tính dù có gửi về hay
            # không — tắt chỉ là tự bịt mắt mình.
            #
            # Model không suy luận thì đây là tham số thừa, đã thử và không lỗi.
            # Muốn tắt thì ghi đè LLM_PROVIDERS trong .env.
            "include_thoughts": True,
        },
        notes=(
            "Cửa sổ ngữ cảnh rất lớn, hợp với RCA vì phải nhét nhiều nhật ký. "
            "Báo lỗi nếu nội dung tin nhắn rỗng."
        ),
    ),
    "anthropic": ProviderConfig(
        package="langchain-anthropic",
        module="langchain_anthropic",
        class_name="ChatAnthropic",
        api_key_field="ANTHROPIC_API_KEY",
        models_url="https://api.anthropic.com/v1/models",
        models_style="anthropic",
        model="claude-sonnet-5",
        fast_model="claude-haiku-4-5-20251001",
        param_map={
            "api_key": "api_key",
            "model": "model",
            "temperature": "temperature",
            "max_tokens": "max_tokens",
            "timeout": "default_request_timeout",  # khác
            "max_retries": "max_retries",
        },
        notes="Gọi công cụ ổn định và bám schema tốt nhất. Đắt hơn.",
    ),
}


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App ---
    APP_NAME: str = "K8s Hub"
    APP_ENV: Literal["local", "dev", "staging", "prod"] = "local"
    DEBUG: bool = Field(default=True, description="Hiện chi tiết lỗi và log dài hơn")
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/k8shub"

    # Alembic cần khoá tư vấn (advisory lock) để hai người không chạy migration
    # cùng lúc, mà bộ gộp kết nối ở chế độ transaction thì không giữ được khoá đó.
    # Với Supabase: dùng cùng host nhưng cổng 5432 (chế độ session).
    # Để trống thì Alembic dùng luôn DATABASE_URL.
    ALEMBIC_DATABASE_URL: str = ""

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Auth ---
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- LLM ---
    # Tên phải khớp một khoá trong LLM_PROVIDERS.
    LLM_PROVIDER: str = Field(
        default="groq", description="Nhà cung cấp AI đang dùng: groq, google hoặc anthropic"
    )

    # Để trống thì lấy model mặc định của nhà cung cấp trong LLM_PROVIDERS.
    LLM_MODEL: str = Field(
        default="", description="Model chính. Để trống thì dùng mặc định của nhà cung cấp"
    )
    LLM_FAST_MODEL: str = Field(
        default="", description="Model rẻ cho việc nhẹ như phân loại ý định"
    )

    LLM_TEMPERATURE: float = Field(
        default=0.0, ge=0.0, le=2.0,
        description="Độ ngẫu nhiên. Để 0 cho kết quả ổn định khi sinh phiếu lệnh",
    )
    LLM_MAX_TOKENS: int = Field(
        default=4096, gt=0, description="Độ dài tối đa của câu trả lời"
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default=60.0, gt=0, description="Chờ AI trả lời tối đa bao nhiêu giây"
    )
    LLM_MAX_RETRIES: int = Field(
        default=3, ge=0, description="Số lần thử lại khi bị nghẽn hoặc lỗi mạng"
    )

    # Catalog nhà cung cấp. Mặc định lấy DEFAULT_LLM_PROVIDERS ở trên.
    # Đặt biến LLM_PROVIDERS trong .env dưới dạng JSON để GHI ĐÈ TỪNG PHẦN,
    # hoặc thêm hẳn nhà cung cấp mới mà không phải sửa file này. Ví dụ:
    #
    #   LLM_PROVIDERS={"groq": {"model": "llama-3.1-8b-instant"}}
    #
    # NoDecode: tự parse JSON trong validator bên dưới, để chịu được khi biến
    # trong .env bị bỏ trống (pydantic-settings mặc định sẽ vỡ ở chuỗi rỗng).
    LLM_PROVIDERS: Annotated[dict[str, ProviderConfig], NoDecode] = Field(
        default_factory=lambda: {
            name: spec.model_copy(deep=True)
            for name, spec in DEFAULT_LLM_PROVIDERS.items()
        },
        description=(
            "Đặc tả từng nhà cung cấp. Ghi đè từng phần, chỉ cần nêu trường muốn đổi. "
            "Dùng để đổi model hoặc thêm hẳn nhà cung cấp mới."
        ),
    )

    # --- Khoá API ---
    # Tên field phải khớp `api_key_field` của nhà cung cấp tương ứng.
    GROQ_API_KEY: str = Field(default="", description="Khoá API của Groq")
    GOOGLE_API_KEY: str = Field(default="", description="Khoá API của Google AI Studio")
    ANTHROPIC_API_KEY: str = Field(default="", description="Khoá API của Anthropic")

    # --- Kubernetes ---
    KUBECONFIG: str | None = None
    K8S_IN_CLUSTER: bool = False
    # read_only | require_approval | auto
    K8S_EXECUTION_MODE: Literal["read_only", "require_approval", "auto"] = Field(
        default="require_approval",
        description=(
            "read_only: chỉ xem · require_approval: phải có người duyệt · "
            "auto: tự thực hiện (NGUY HIỂM)"
        ),
    )
    K8S_ALLOWED_NAMESPACES: list[str] = Field(
        default=[],
        description="Chỉ được thao tác trong các khu vực này. Để trống là cho phép tất cả",
    )

    # --- Observability data sources ---
    PROMETHEUS_URL: str = Field(
        default="http://localhost:9090", description="Địa chỉ kho số liệu, dùng cho chẩn đoán"
    )
    LOKI_URL: str = Field(
        default="http://localhost:3100", description="Địa chỉ kho nhật ký, dùng cho chẩn đoán"
    )

    # --- Langfuse ---
    LANGFUSE_HOST: str = Field(
        default="http://localhost:3001", description="Địa chỉ hệ thống theo dõi AI"
    )
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Khoá công khai Langfuse")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Khoá bí mật Langfuse")
    LANGFUSE_ENABLED: bool = Field(
        default=False, description="Có ghi lại diễn biến mỗi lần gọi AI hay không"
    )

    # -----------------------------------------------------------------------

    @field_validator("LLM_PROVIDERS", mode="before")
    @classmethod
    def _merge_with_defaults(cls, value: Any) -> Any:
        """Giá trị từ .env GHI ĐÈ TỪNG PHẦN lên mặc định, không thay thế cả cụm.

        Nhờ vậy chỉ cần ghi `{"groq": {"model": "..."}}` là đổi được đúng một
        trường, không phải chép lại toàn bộ đặc tả.

        Biến để trống trong .env thì coi như không ghi đè gì.
        """
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {name: spec.model_dump() for name, spec in DEFAULT_LLM_PROVIDERS.items()}
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"LLM_PROVIDERS phải là JSON hợp lệ hoặc để trống. Lỗi: {exc}"
                ) from exc

        if not isinstance(value, dict):
            return value

        merged: dict[str, Any] = {
            name: spec.model_dump() for name, spec in DEFAULT_LLM_PROVIDERS.items()
        }
        for name, override in value.items():
            if isinstance(override, ProviderConfig):
                override = override.model_dump()
            if not isinstance(override, dict):
                merged[name] = override
                continue
            if name in merged:
                merged[name] = {**merged[name], **override}
            else:
                merged[name] = override
        return merged

    # --- Tiện ích LLM ---------------------------------------------------

    def llm_provider(self, name: str | None = None) -> ProviderConfig:
        """Đặc tả của nhà cung cấp đang dùng (hoặc của `name` nếu truyền vào)."""
        key = name or self.LLM_PROVIDER
        if key not in self.LLM_PROVIDERS:
            available = ", ".join(sorted(self.LLM_PROVIDERS)) or "(trống)"
            raise ValueError(
                f"Không có nhà cung cấp LLM {key!r}. Hiện có: {available}. "
                f"Kiểm tra LLM_PROVIDER trong .env."
            )
        return self.LLM_PROVIDERS[key]

    def llm_model_name(self, *, provider: str | None = None, profile: str = "default") -> str:
        """Tên model theo hồ sơ. LLM_MODEL / LLM_FAST_MODEL trong .env được ưu tiên."""
        spec = self.llm_provider(provider)
        if profile == "fast":
            return self.LLM_FAST_MODEL or spec.fast_model or spec.model
        return self.LLM_MODEL or spec.model

    def llm_api_key(self, *, provider: str | None = None) -> str:
        """Khoá API của nhà cung cấp, đọc theo `api_key_field` của nó."""
        spec = self.llm_provider(provider)
        key = str(getattr(self, spec.api_key_field, "") or "").strip()
        if not key:
            raise ValueError(
                f"Thiếu khoá API cho nhà cung cấp {provider or self.LLM_PROVIDER!r}. "
                f"Đặt {spec.api_key_field} trong file .env."
            )
        return key




# ---------------------------------------------------------------------------
# Trường được phép đổi lúc chạy (từ giao diện web)
# ---------------------------------------------------------------------------

#: Đổi được ngay khi hệ thống đang chạy, không cần khởi động lại.
RUNTIME_EDITABLE: frozenset[str] = frozenset(
    {
        "DEBUG",
        # LLM
        "LLM_PROVIDER",
        "LLM_MODEL",
        "LLM_FAST_MODEL",
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        "LLM_PROVIDERS",
        # Kubernetes — đổi được vì chỉ ảnh hưởng lúc kiểm tra từng thao tác
        "K8S_EXECUTION_MODE",
        "K8S_ALLOWED_NAMESPACES",
        # Nguồn dữ liệu quan sát
        "PROMETHEUS_URL",
        "LOKI_URL",
        # Langfuse
        "LANGFUSE_ENABLED",
        "LANGFUSE_HOST",
    }
)

#: Cũng đổi được nhưng là bí mật: KHÔNG trả về giao diện, KHÔNG ghi vào log.
RUNTIME_EDITABLE_SECRETS: frozenset[str] = frozenset(
    {
        "GROQ_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
    }
)

#: Tập đầy đủ những trường giao diện được phép ghi.
ALL_EDITABLE: frozenset[str] = RUNTIME_EDITABLE | RUNTIME_EDITABLE_SECRETS

# Những trường còn lại (DATABASE_URL, REDIS_URL, JWT_SECRET, APP_ENV...) chỉ đọc
# từ .env lúc khởi động — đổi lúc chạy không có ý nghĩa hoặc không an toàn.


class ConfigUpdateError(ValueError):
    """Giá trị gửi từ giao diện không hợp lệ. Không có thay đổi nào được áp dụng."""


# ---------------------------------------------------------------------------
# Nơi lưu phần ghi đè
# ---------------------------------------------------------------------------


class OverrideStore(Protocol):
    """Nơi cất phần cấu hình người dùng đổi trên web, để khởi động lại vẫn còn.

    Bản mặc định chỉ giữ trong bộ nhớ. Khi có bảng dữ liệu thì viết một lớp
    lưu xuống Postgres rồi gọi `set_override_store()` lúc khởi động.
    """

    def load(self) -> dict[str, Any]: ...

    def save(self, values: dict[str, Any]) -> None: ...


class MemoryOverrideStore:
    """Giữ trong bộ nhớ — mất khi tắt tiến trình."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        return dict(self._values)

    def save(self, values: dict[str, Any]) -> None:
        self._values = dict(values)


# ---------------------------------------------------------------------------
# Trạng thái toàn cục
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_base: Settings | None = None          # đọc từ .env, chỉ một lần
_effective: Settings | None = None     # .env + phần ghi đè
_overrides: dict[str, Any] = {}
_store: OverrideStore = MemoryOverrideStore()
_version: int = 0
_callbacks: list[Callable[[], None]] = []


def _compose(base: Settings, overrides: dict[str, Any]) -> Settings:
    """Dựng cấu hình hiệu lực = giá trị từ .env, đè lên bởi phần ghi đè.

    Ném ConfigUpdateError nếu có giá trị không hợp lệ — khi đó KHÔNG áp dụng
    gì cả, cấu hình đang chạy giữ nguyên.
    """
    if not overrides:
        return base

    data = base.model_dump()

    for name, value in overrides.items():
        if name == "LLM_PROVIDERS":
            # Ghi đè từng phần lên danh sách đang có, không thay cả cụm.
            merged = dict(data.get("LLM_PROVIDERS") or {})
            for provider_name, patch in (value or {}).items():
                if isinstance(patch, dict) and provider_name in merged:
                    merged[provider_name] = {**merged[provider_name], **patch}
                else:
                    merged[provider_name] = patch
            data["LLM_PROVIDERS"] = merged
        else:
            data[name] = value

    try:
        return Settings(_env_file=None, **data)
    except Exception as exc:  # ValidationError và mọi lỗi dựng khác
        raise ConfigUpdateError(f"Cấu hình không hợp lệ: {exc}") from exc


def _rebuild_locked() -> Settings:
    """Dựng lại cấu hình hiệu lực. Chỉ gọi khi đang giữ _lock."""
    global _effective, _version
    assert _base is not None
    _effective = _compose(_base, _overrides)
    _version += 1
    return _effective


def _notify() -> None:
    with _lock:
        listeners = list(_callbacks)
    for callback in listeners:
        callback()


def _ensure_loaded() -> Settings:
    global _base, _effective, _overrides
    if _effective is not None:
        return _effective
    with _lock:
        if _effective is None:
            _base = Settings()
            _overrides = {
                name: value for name, value in _store.load().items() if name in ALL_EDITABLE
            }
            try:
                _effective = _compose(_base, _overrides)
            except ConfigUpdateError:
                # Dữ liệu đã lưu bị hỏng thì bỏ qua, chạy bằng .env thuần.
                _overrides = {}
                _effective = _base
        return _effective


# ---------------------------------------------------------------------------
# API công khai
# ---------------------------------------------------------------------------


def get_settings() -> Settings:
    """Cấu hình đang có hiệu lực (.env + phần đổi trên web)."""
    return _ensure_loaded()


def get_base_settings() -> Settings:
    """Chỉ giá trị từ .env, chưa tính phần ghi đè. Dùng cho nút khôi phục."""
    _ensure_loaded()
    assert _base is not None
    return _base


def runtime_overrides(*, redact_secrets: bool = True) -> dict[str, Any]:
    """Những trường đang bị ghi đè so với .env."""
    _ensure_loaded()
    with _lock:
        values = dict(_overrides)
    if redact_secrets:
        for name in values:
            if name in RUNTIME_EDITABLE_SECRETS:
                values[name] = "***"
    return values


def apply_overrides(values: dict[str, Any], *, replace: bool = False) -> Settings:
    """Áp dụng thay đổi từ giao diện web.

    Args:
        values:  {tên trường: giá trị mới}. Đặt None để bỏ ghi đè trường đó,
                 trả nó về giá trị trong .env.
        replace: True thì thay toàn bộ phần ghi đè, False thì trộn vào cái đang có.

    Raises:
        ConfigUpdateError: tên trường không được phép đổi, hoặc giá trị sai kiểu.
                           Khi đó KHÔNG có thay đổi nào được áp dụng.
    """
    _ensure_loaded()

    khong_cho_phep = sorted(set(values) - ALL_EDITABLE)
    if khong_cho_phep:
        raise ConfigUpdateError(
            f"Không được đổi lúc chạy: {', '.join(khong_cho_phep)}. "
            f"Những trường này chỉ đọc từ .env lúc khởi động."
        )

    with _lock:
        assert _base is not None
        candidate = {} if replace else dict(_overrides)
        for name, value in values.items():
            if value is None:
                candidate.pop(name, None)
            else:
                candidate[name] = value

        # Validate TRƯỚC khi ghi nhận — sai thì không đụng tới cấu hình đang chạy.
        _compose(_base, candidate)

        globals()["_overrides"] = candidate
        _store.save(candidate)
        result = _rebuild_locked()

    _notify()
    return result


def clear_overrides() -> Settings:
    """Bỏ hết phần đổi trên web, quay về đúng .env."""
    return apply_overrides({}, replace=True)


def reload_from_env() -> Settings:
    """Đọc lại .env từ đĩa. Phần đổi trên web được giữ và áp lại lên trên.

    Dùng sau khi triển khai bản mới hoặc sửa .env bằng tay. Không tự động —
    phải gọi tường minh.
    """
    global _base
    _ensure_loaded()
    with _lock:
        _base = Settings()
        result = _rebuild_locked()
    _notify()
    return result


def set_override_store(store: OverrideStore) -> None:
    """Đổi nơi lưu phần ghi đè (mặc định là bộ nhớ).

    Gọi lúc khởi động để nạp lại những gì người dùng đã đổi ở phiên trước.
    """
    global _store, _effective
    with _lock:
        _store = store
        _effective = None  # buộc nạp lại từ store mới
    _ensure_loaded()
    _notify()


def on_reload(callback: Callable[[], None]) -> Callable[[], None]:
    """Đăng ký hàm được gọi mỗi khi cấu hình đổi.

    Dùng cho module có bộ nhớ đệm dựng từ cấu hình (client LLM, engine DB...):

        @on_reload
        def _clear_cache() -> None:
            _model_cache.clear()
    """
    with _lock:
        _callbacks.append(callback)
    return callback


def settings_version() -> int:
    """Tăng thêm 1 sau mỗi lần cấu hình đổi. Dùng làm khoá cho bộ nhớ đệm."""
    _ensure_loaded()
    return _version


def _jsonable(value: Any) -> Any:
    """Đổi model Pydantic lồng nhau thành dict thuần để trả về JSON."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _field_type(annotation: Any) -> tuple[str, list[Any] | None]:
    """Suy ra kiểu và danh sách lựa chọn để giao diện dựng đúng ô nhập."""
    if get_origin(annotation) is Literal:
        return "enum", list(get_args(annotation))

    # Bóc Annotated[...] và Optional[...]
    args = get_args(annotation)
    if get_origin(annotation) is not None and args:
        if annotation is not None and get_origin(annotation) in (list, dict):
            return ("list" if get_origin(annotation) is list else "object"), None
        for arg in args:
            if arg is type(None):
                continue
            kieu, lua_chon = _field_type(arg)
            if kieu != "string":
                return kieu, lua_chon

    if annotation is bool:
        return "boolean", None
    if annotation is int:
        return "integer", None
    if annotation is float:
        return "number", None
    if annotation is str:
        return "string", None
    return "string", None


def _field_bounds(info: Any) -> dict[str, Any]:
    """Lấy giới hạn min/max từ ràng buộc của Pydantic (ge, le, gt, lt)."""
    bounds: dict[str, Any] = {}
    for meta in getattr(info, "metadata", []) or []:
        for ten, khoa in (("ge", "minimum"), ("gt", "exclusive_minimum"),
                          ("le", "maximum"), ("lt", "exclusive_maximum")):
            value = getattr(meta, ten, None)
            if value is not None:
                bounds[khoa] = value
    return bounds


def editable_fields(*, include_secrets: bool = True) -> list[dict[str, Any]]:
    """Mô tả các trường cho giao diện web dựng form.

    Giá trị của trường bí mật KHÔNG bao giờ được trả ra — chỉ báo đã đặt hay chưa.
    """
    config = _ensure_loaded()
    base = get_base_settings()
    names = ALL_EDITABLE if include_secrets else RUNTIME_EDITABLE

    out: list[dict[str, Any]] = []
    for name in sorted(names):
        info = Settings.model_fields.get(name)
        if info is None:
            continue
        is_secret = name in RUNTIME_EDITABLE_SECRETS
        current = getattr(config, name)
        kieu, lua_chon = _field_type(info.annotation)
        if is_secret:
            kieu = "secret"
        elif name == "LLM_PROVIDER":
            # Danh sách động theo những nhà cung cấp đang khai báo.
            kieu, lua_chon = "enum", sorted(config.LLM_PROVIDERS)

        out.append(
            {
                "name": name,
                "type": kieu,
                "options": lua_chon,
                "secret": is_secret,
                "description": info.description or "",
                "value": None if is_secret else _jsonable(current),
                "is_set": bool(current) if is_secret else None,
                "env_value": None if is_secret else _jsonable(getattr(base, name)),
                "overridden": name in _overrides,
                **_field_bounds(info),
            }
        )
    return out


class _SettingsProxy:
    """Cho phép `from app.core.config import settings` luôn thấy giá trị mới nhất.

    Nếu gán `settings = Settings()` một lần lúc import thì sau khi người dùng đổi
    cấu hình trên web, mọi module vẫn cầm object cũ. Proxy này luôn hỏi lại.
    """

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        return getattr(get_settings(), name)

    def __repr__(self) -> str:
        return f"<settings v{_version} {get_settings().APP_ENV}>"


settings: Any = _SettingsProxy()


__all__ = [
    "ALL_EDITABLE",
    "CANONICAL_LLM_PARAMS",
    "DEFAULT_LLM_PROVIDERS",
    "RUNTIME_EDITABLE",
    "RUNTIME_EDITABLE_SECRETS",
    "ConfigUpdateError",
    "MemoryOverrideStore",
    "OverrideStore",
    "ProviderConfig",
    "Settings",
    "apply_overrides",
    "clear_overrides",
    "editable_fields",
    "get_base_settings",
    "get_settings",
    "on_reload",
    "reload_from_env",
    "runtime_overrides",
    "set_override_store",
    "settings",
    "settings_version",
]
