"""Application configuration — the single source of truth for the whole system.

Two layers stacked on top of each other:

    .env  (STATIC, read once at startup)
      +
    what the user changes in the web UI  (LIVE, changed at runtime)
      =
    effective configuration  ->  every other module

  - `.env` holds what does not change at runtime: database URL, JWT secret,
    environment. Editing the file does NOT take effect automatically — call
    `reload_from_env()`.
  - The web UI changes the fields in `RUNTIME_EDITABLE` via `apply_overrides()`.
    Values are validated before being applied; invalid input leaves the running
    configuration untouched.
  - `config.py` is the ONLY configuration layer. No module may read os.environ
    or its own config file — everything goes through here.

Usage:

    from app.core.config import settings
    print(settings.LLM_TEMPERATURE)  # always the latest value

Modules that cache something built from the configuration register an
`on_reload()` callback to clear that cache whenever the configuration changes.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, Literal, Protocol, get_args, get_origin

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ---------------------------------------------------------------------------
# LLM provider specs
# ---------------------------------------------------------------------------


class ProviderConfig(BaseModel):
    """Everything needed to build a chat model for one provider.

    `param_map` absorbs the differences between providers: keys are the
    system's canonical parameter names, values are that class's real parameter
    names. For example, Gemini calls `max_tokens` `max_output_tokens`.
    """

    package: str = Field(description="pip package name, used in the 'not installed' hint")
    module: str = Field(description="Import path, e.g. langchain_groq")
    class_name: str = Field(description="Class name inside that module")
    api_key_field: str = Field(description="Name of the API key field in Settings")

    model: str = Field(description="Default model")
    fast_model: str = Field(default="", description="Cheap model for light work")

    param_map: dict[str, str] = Field(
        description="canonical name -> the provider's real parameter name",
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-specific arguments passed straight to the constructor",
    )

    supports_tool_calling: bool = True
    supports_streaming: bool = True
    supports_structured_output: bool = True
    notes: str = ""

    # --- Listing models straight from the provider ---
    #
    # Declared here instead of hard-coded: adding a provider only needs one
    # more entry in DEFAULT_LLM_PROVIDERS, no other file changes.
    models_url: str = Field(
        default="",
        description="Model listing API. Leave empty to only use the models declared here.",
    )
    models_style: Literal["openai", "google"] = Field(
        default="openai",
        description=(
            "Response shape and auth scheme of the model listing API. "
            "'openai' (Groq and compatible APIs): Bearer token, results under 'data'. "
            "'google': API key as a query param, results under 'models'."
        ),
    )


# The system's canonical parameters. If a provider has no equivalent, drop that
# key from its param_map and it will not be passed to the constructor.
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
        model="openai/gpt-oss-120b",
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
            "Fastest and cheapest. Only some models support tool calling. "
            "Small models tend to invent tool names; avoid them for generating action plans."
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
            "api_key": "google_api_key",      # differs: not api_key
            "model": "model",
            "temperature": "temperature",
            "max_tokens": "max_output_tokens",  # differs: not max_tokens
            "timeout": "timeout",
            "max_retries": "max_retries",
        },
        extra={
            # Gemini DOES reason but does not send the reasoning back by
            # default, so the chat could not show "Thinking". Turn it on.
            #
            # It costs nothing extra: reasoning tokens are billed whether they
            # are returned or not — turning it off only blinds us.
            #
            # For non-reasoning models this is a no-op; tested, no errors.
            "include_thoughts": True,
        },
        notes=(
            "Very large context window, a good fit for RCA which needs lots of logs. "
            "Errors out if a message has empty content."
        ),
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
    DEBUG: bool = Field(default=True, description="Show detailed errors and more verbose logs")
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # --- Database ---
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/k8shub"

    # Alembic needs an advisory lock so two people cannot run migrations at the
    # same time, and a transaction-mode connection pooler cannot hold that lock.
    # With Supabase: same host but port 5432 (session mode).
    # Leave empty to make Alembic use DATABASE_URL.
    ALEMBIC_DATABASE_URL: str = ""

    # --- Redis ---
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Auth ---
    JWT_SECRET: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    # Refresh tokens live much longer than access tokens — they are only used
    # to obtain a new access token, never sent with every request. A leak does
    # less damage because they rotate: every refresh revokes the old token in
    # the database (refresh_tokens table) and issues a new one — reusing an old
    # one is a sign of theft.
    JWT_REFRESH_EXPIRE_DAYS: int = 30

    # First administrator account. Self-registration always creates the 'user'
    # role, so there must be another way to create the first admin. `lifespan`
    # checks at startup: if nobody has the admin role yet, this account is
    # created (or promoted). Leave empty to skip that step and create an admin
    # some other way (e.g. editing the database once).
    ADMIN_BOOTSTRAP_EMAIL: str = ""
    ADMIN_BOOTSTRAP_PASSWORD: str = ""

    # --- LLM ---
    # Only model-call parameters. Provider/model selection: see `llm_default_provider`.
    LLM_TEMPERATURE: float = Field(
        default=0.0, ge=0.0, le=2.0,
        description="Randomness. Keep at 0 for stable output when generating action plans",
    )
    LLM_MAX_TOKENS: int = Field(
        default=4096, gt=0, description="Maximum length of a response"
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default=60.0, gt=0, description="Maximum seconds to wait for the model to respond"
    )
    LLM_MAX_RETRIES: int = Field(
        default=3, ge=0, description="Retries on rate limiting or network errors"
    )

    # --- API keys ---
    # Field names must match the provider's `api_key_field`.
    GROQ_API_KEY: str = Field(default="", description="Groq API key")
    GOOGLE_API_KEY: str = Field(default="", description="Google AI Studio API key")

    # --- Kubernetes ---
    KUBECONFIG: str | None = None
    K8S_IN_CLUSTER: bool = False
    # read_only | require_approval | auto
    K8S_EXECUTION_MODE: Literal["read_only", "require_approval", "auto"] = Field(
        default="require_approval",
        description=(
            "read_only: view only · require_approval: a human must approve · "
            "auto: executes on its own (DANGEROUS)"
        ),
    )
    K8S_ALLOWED_NAMESPACES: list[str] = Field(
        default=[],
        description="Only operate in these namespaces. Leave empty to allow all",
    )

    # --- Observability data sources ---
    PROMETHEUS_URL: str = Field(
        default="http://localhost:9090", description="Metrics store URL, used for diagnosis"
    )
    LOKI_URL: str = Field(
        default="http://localhost:3100", description="Log store URL, used for diagnosis"
    )

    # --- Langfuse ---
    LANGFUSE_HOST: str = Field(
        default="http://localhost:3001", description="LLM tracing server URL"
    )
    LANGFUSE_PUBLIC_KEY: str = Field(default="", description="Langfuse public key")
    LANGFUSE_SECRET_KEY: str = Field(default="", description="Langfuse secret key")
    LANGFUSE_ENABLED: bool = Field(
        default=False, description="Record a trace of every model call"
    )

    # --- LLM helpers ----------------------------------------------------
    #
    # Provider and model are NOT configuration in .env or on the Settings page.
    # The user picks them per chat turn in the model picker, and the model list
    # comes straight from the provider's API (app/integrations/llm/catalog.py).
    # The four old variables — LLM_PROVIDER, LLM_MODEL, LLM_FAST_MODEL,
    # LLM_PROVIDERS — only drifted from what the UI showed, so they were removed.
    #
    # Provider specs (which class, where to list models, parameter names) are
    # still needed — the catalog reads them — but they are CODE, in
    # DEFAULT_LLM_PROVIDERS above. Add a provider by adding an entry there.

    @property
    def LLM_PROVIDERS(self) -> dict[str, ProviderConfig]:  # noqa: N802 — keeps the old name for callers
        return DEFAULT_LLM_PROVIDERS

    def llm_default_provider(self) -> str:
        """Provider used when the user has not picked one.

        It is the FIRST one with an API key set, in DEFAULT_LLM_PROVIDERS order.
        Derived instead of read from an LLM_PROVIDER variable: that variable
        could point at a provider without a key, breaking the very first chat
        message. The frontend (`use-models.ts`) applies the same rule, so both
        sides always agree.

        With no key set at all, returns the first provider — the "missing API
        key" error raised when calling the model then names the variable to set.
        """
        for name, spec in DEFAULT_LLM_PROVIDERS.items():
            if str(getattr(self, spec.api_key_field, "") or "").strip():
                return name
        return next(iter(DEFAULT_LLM_PROVIDERS))

    def llm_provider(self, name: str | None = None) -> ProviderConfig:
        """Spec of provider `name`, or of the default provider."""
        key = name or self.llm_default_provider()
        if key not in DEFAULT_LLM_PROVIDERS:
            available = ", ".join(sorted(DEFAULT_LLM_PROVIDERS)) or "(none)"
            raise ValueError(f"Unknown LLM provider {key!r}. Available: {available}.")
        return DEFAULT_LLM_PROVIDERS[key]

    def llm_model_name(self, *, provider: str | None = None, profile: str = "default") -> str:
        """The provider's default model — used when a chat turn does not specify one."""
        spec = self.llm_provider(provider)
        if profile == "fast":
            return spec.fast_model or spec.model
        return spec.model

    def llm_api_key(self, *, provider: str | None = None) -> str:
        """The provider's API key, read via its `api_key_field`."""
        spec = self.llm_provider(provider)
        key = str(getattr(self, spec.api_key_field, "") or "").strip()
        if not key:
            raise ValueError(
                f"Missing API key for provider {provider or self.llm_default_provider()!r}. "
                f"Set {spec.api_key_field} in Settings or in the .env file."
            )
        return key


# ---------------------------------------------------------------------------
# Fields that may change at runtime (from the web UI)
# ---------------------------------------------------------------------------

#: Can be changed while the system is running, no restart needed.
RUNTIME_EDITABLE: frozenset[str] = frozenset(
    {
        "DEBUG",
        # LLM — call parameters only; provider/model are picked in the chat
        "LLM_TEMPERATURE",
        "LLM_MAX_TOKENS",
        "LLM_TIMEOUT_SECONDS",
        "LLM_MAX_RETRIES",
        # Kubernetes — editable because it only affects per-operation checks
        "K8S_EXECUTION_MODE",
        "K8S_ALLOWED_NAMESPACES",
        # Observability data sources
        "PROMETHEUS_URL",
        "LOKI_URL",
        # LANGFUSE_* is DELIBERATELY not here: the Langfuse SDK keeps a
        # singleton keyed by public key, so rebuilding the client with another
        # host or secret returns the old object and silently ignores the new
        # values. Allowing edits in the UI would promise something that does
        # not happen. Change them in .env and restart.
    }
)

#: Also editable, but secret: NEVER returned to the UI, NEVER logged.
RUNTIME_EDITABLE_SECRETS: frozenset[str] = frozenset(
    {
        "GROQ_API_KEY",
        "GOOGLE_API_KEY",
    }
)

#: Every field the UI may write.
ALL_EDITABLE: frozenset[str] = RUNTIME_EDITABLE | RUNTIME_EDITABLE_SECRETS

# The remaining fields (DATABASE_URL, REDIS_URL, JWT_SECRET, APP_ENV, LANGFUSE_*)
# are only read from .env at startup — changing them at runtime is meaningless,
# unsafe, or not supported by the underlying library.


class ConfigUpdateError(ValueError):
    """The value sent from the UI is invalid. No change was applied."""


# ---------------------------------------------------------------------------
# Where overrides are stored
# ---------------------------------------------------------------------------


class OverrideStore(Protocol):
    """Where the UI-made configuration changes are kept, to survive restarts.

    The default keeps them in memory only. Once there is a table for it, write
    a Postgres-backed class and call `set_override_store()` at startup.
    """

    def load(self) -> dict[str, Any]: ...

    def save(self, values: dict[str, Any]) -> None: ...


class MemoryOverrideStore:
    """Kept in memory — lost when the process stops."""

    def __init__(self) -> None:
        self._values: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        return dict(self._values)

    def save(self, values: dict[str, Any]) -> None:
        self._values = dict(values)


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_lock = threading.RLock()
_base: Settings | None = None          # read from .env, once
_effective: Settings | None = None     # .env + overrides
_overrides: dict[str, Any] = {}
_store: OverrideStore = MemoryOverrideStore()
_version: int = 0
_callbacks: list[Callable[[], None]] = []


def _compose(base: Settings, overrides: dict[str, Any]) -> Settings:
    """Build the effective configuration = values from .env, overlaid by overrides.

    Raises ConfigUpdateError on any invalid value — in that case NOTHING is
    applied and the running configuration stays as it was.
    """
    if not overrides:
        return base

    data = base.model_dump()

    for name, value in overrides.items():
        data[name] = value

    try:
        return Settings(_env_file=None, **data)
    except Exception as exc:  # ValidationError and any other build error
        raise ConfigUpdateError(f"Invalid configuration: {exc}") from exc


def _rebuild_locked() -> Settings:
    """Rebuild the effective configuration. Call only while holding _lock."""
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
                # Stored data is corrupt: ignore it and run on plain .env.
                _overrides = {}
                _effective = _base
        return _effective


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_settings() -> Settings:
    """The effective configuration (.env + changes made in the UI)."""
    return _ensure_loaded()


def get_base_settings() -> Settings:
    """Values from .env only, without overrides. Used by the "restore" button."""
    _ensure_loaded()
    assert _base is not None
    return _base


def runtime_overrides(*, redact_secrets: bool = True) -> dict[str, Any]:
    """Fields currently overridden relative to .env."""
    _ensure_loaded()
    with _lock:
        values = dict(_overrides)
    if redact_secrets:
        for name in values:
            if name in RUNTIME_EDITABLE_SECRETS:
                values[name] = "***"
    return values


def apply_overrides(values: dict[str, Any], *, replace: bool = False) -> Settings:
    """Apply changes coming from the web UI.

    Args:
        values:  {field name: new value}. Set None to drop the override and
                 go back to the value in .env.
        replace: True replaces all overrides, False merges into the current ones.

    Raises:
        ConfigUpdateError: the field is not editable, or the value has the wrong
                           type. In that case NO change is applied.
    """
    _ensure_loaded()

    # Two separate cases so the message tells the truth: a field that does not
    # exist (e.g. the removed LLM_PROVIDER) is not the same as a real field that
    # is only read at startup.
    unknown = sorted(set(values) - set(Settings.model_fields))
    if unknown:
        raise ConfigUpdateError(f"Unknown configuration field: {', '.join(unknown)}.")

    not_editable = sorted(set(values) - ALL_EDITABLE)
    if not_editable:
        raise ConfigUpdateError(
            f"Cannot be changed at runtime: {', '.join(not_editable)}. "
            f"These fields are only read from .env at startup."
        )

    with _lock:
        assert _base is not None
        candidate = {} if replace else dict(_overrides)
        for name, value in values.items():
            if value is None:
                candidate.pop(name, None)
            else:
                candidate[name] = value

        # Validate BEFORE committing — invalid input never touches the running config.
        _compose(_base, candidate)

        globals()["_overrides"] = candidate
        _store.save(candidate)
        result = _rebuild_locked()

    _notify()
    return result


def clear_overrides() -> Settings:
    """Drop every UI change and go back to exactly what .env says."""
    return apply_overrides({}, replace=True)


def reload_from_env() -> Settings:
    """Re-read .env from disk. UI changes are kept and re-applied on top.

    Use after deploying a new version or editing .env by hand. Not automatic —
    must be called explicitly.
    """
    global _base
    _ensure_loaded()
    with _lock:
        _base = Settings()
        result = _rebuild_locked()
    _notify()
    return result


def set_override_store(store: OverrideStore) -> None:
    """Change where overrides are stored (memory by default).

    Call at startup to reload what users changed in a previous session.
    """
    global _store, _effective
    with _lock:
        _store = store
        _effective = None  # force a reload from the new store
    _ensure_loaded()
    _notify()


def on_reload(callback: Callable[[], None]) -> Callable[[], None]:
    """Register a function to be called whenever the configuration changes.

    For modules with caches built from the configuration (LLM client, DB engine...):

        @on_reload
        def _clear_cache() -> None:
            _model_cache.clear()
    """
    with _lock:
        _callbacks.append(callback)
    return callback


def settings_version() -> int:
    """Incremented on every configuration change. Useful as a cache key."""
    _ensure_loaded()
    return _version


def _jsonable(value: Any) -> Any:
    """Turn nested Pydantic models into plain dicts for JSON responses."""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def _field_type(annotation: Any) -> tuple[str, list[Any] | None]:
    """Infer the type and choices so the UI renders the right input."""
    if get_origin(annotation) is Literal:
        return "enum", list(get_args(annotation))

    # Unwrap Annotated[...] and Optional[...]
    args = get_args(annotation)
    if get_origin(annotation) is not None and args:
        if annotation is not None and get_origin(annotation) in (list, dict):
            return ("list" if get_origin(annotation) is list else "object"), None
        for arg in args:
            if arg is type(None):
                continue
            kind, choices = _field_type(arg)
            if kind != "string":
                return kind, choices

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
    """Read min/max bounds from Pydantic constraints (ge, le, gt, lt)."""
    bounds: dict[str, Any] = {}
    for meta in getattr(info, "metadata", []) or []:
        for attr, key in (("ge", "minimum"), ("gt", "exclusive_minimum"),
                          ("le", "maximum"), ("lt", "exclusive_maximum")):
            value = getattr(meta, attr, None)
            if value is not None:
                bounds[key] = value
    return bounds


def editable_fields(*, include_secrets: bool = True) -> list[dict[str, Any]]:
    """Describe the fields so the web UI can build the form.

    Secret values are NEVER returned — only whether they are set.
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
        kind, choices = _field_type(info.annotation)
        if is_secret:
            kind = "secret"

        out.append(
            {
                "name": name,
                "type": kind,
                "options": choices,
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
    """Makes `from app.core.config import settings` always see the latest values.

    Assigning `settings = Settings()` once at import time would leave every
    module holding the old object after a user changes the configuration in the
    UI. This proxy always asks again.
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
