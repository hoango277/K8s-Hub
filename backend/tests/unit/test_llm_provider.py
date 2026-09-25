"""Tests for the LLM provider wrapper and the configuration hot-reload mechanism.

No network calls, no need to install langchain-groq / langchain-google-genai:
a fake module is used to inspect the parameter mapping — that is where
mistakes are most likely.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from app.core import config as C
from app.core.config import ProviderConfig, Settings
from app.integrations.llm import provider as P

# ---------------------------------------------------------------------------
# Fake provider
# ---------------------------------------------------------------------------


class FakeChatModel:
    """Records exactly the kwargs it received so the tests can inspect them."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs


@pytest.fixture
def fake_module() -> Any:
    mod = types.ModuleType("fake_llm_pkg")
    mod.FakeChatModel = FakeChatModel  # type: ignore[attr-defined]
    sys.modules["fake_llm_pkg"] = mod
    yield mod
    sys.modules.pop("fake_llm_pkg", None)


FAKE_SPEC = ProviderConfig(
    package="fake-llm-pkg",
    module="fake_llm_pkg",
    class_name="FakeChatModel",
    api_key_field="GROQ_API_KEY",  # borrow a field that already exists in Settings
    model="big-model",
    fast_model="small-model",
    param_map={
        "api_key": "secret",
        "model": "model_name",
        "temperature": "temp",
        "max_tokens": "output_limit",
        "timeout": "deadline",
        "max_retries": "retries",
    },
    extra={"vendor_flag": True},
)


@pytest.fixture(autouse=True)
def _restore_provider_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """`fake_settings` patches the provider catalog directly — restore it after each test."""
    monkeypatch.setattr(C, "DEFAULT_LLM_PROVIDERS", dict(C.DEFAULT_LLM_PROVIDERS))


def fake_settings(spec: ProviderConfig = FAKE_SPEC, **kwargs: Any) -> Settings:
    """Settings whose default provider is the fake provider.

    The provider catalog now lives in code (no more LLM_PROVIDERS in .env), so
    the fake provider is plugged in by replacing the whole catalog. It is the
    ONLY entry, so `llm_default_provider()` picks it.
    """
    C.DEFAULT_LLM_PROVIDERS = {"fake": spec}  # the autouse fixture restores it
    base: dict[str, Any] = {"_env_file": None, "GROQ_API_KEY": "sk-test"}
    base.update(kwargs)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Default specs in config.py
# ---------------------------------------------------------------------------


def test_has_all_providers() -> None:
    assert set(C.DEFAULT_LLM_PROVIDERS) == {"groq", "google"}


@pytest.mark.parametrize("name", ["groq", "google"])
def test_each_provider_is_fully_declared(name: str) -> None:
    spec = C.DEFAULT_LLM_PROVIDERS[name]
    assert spec.model, f"{name} is missing a default model"
    assert spec.fast_model, f"{name} is missing a cheap model"
    assert spec.supports_tool_calling, f"{name} must support tool calling"
    # A missing mapping means the parameter is silently dropped — all must be present.
    assert set(spec.param_map) == set(C.CANONICAL_LLM_PARAMS), f"{name} mapping incomplete"
    # The API key must point to a field that actually exists in Settings.
    assert spec.api_key_field in Settings.model_fields, f"{name} points to the wrong key field"


def test_parameter_names_differ_between_providers() -> None:
    """This is exactly why the wrapper exists — providers name things differently."""
    d = C.DEFAULT_LLM_PROVIDERS
    assert d["groq"].param_map["max_tokens"] == "max_tokens"
    assert d["google"].param_map["max_tokens"] == "max_output_tokens"
    assert d["google"].param_map["api_key"] == "google_api_key"


# ---------------------------------------------------------------------------
# Parameter mapping
# ---------------------------------------------------------------------------


def test_renames_parameters_correctly(fake_module: Any) -> None:
    llm = P.create_chat_model(config=fake_settings())
    assert llm.kwargs == {
        "secret": "sk-test",
        "model_name": "big-model",
        "temp": 0.0,
        "output_limit": 4096,
        "deadline": 60.0,
        "retries": 3,
        "vendor_flag": True,  # from `extra`
    }


def test_fast_profile_switches_model(fake_module: Any) -> None:
    llm = P.create_chat_model(config=fake_settings(), profile="fast")
    assert llm.kwargs["model_name"] == "small-model"


def test_legacy_llm_env_vars_are_ignored(fake_module: Any) -> None:
    """LLM_MODEL/LLM_PROVIDER left over in an old .env must have no effect —
    the model is chosen per chat turn, defaulting to the provider spec."""
    cfg = fake_settings(LLM_MODEL="model-from-env", LLM_PROVIDER="google")
    llm = P.create_chat_model(config=cfg)
    assert llm.kwargs["model_name"] == "big-model"
    assert cfg.llm_default_provider() == "fake"


def test_explicit_parameters_win_over_settings(fake_module: Any) -> None:
    llm = P.create_chat_model(
        config=fake_settings(LLM_TEMPERATURE=0.1),
        model="custom-model",
        temperature=0.7,
        max_tokens=100,
    )
    assert llm.kwargs["model_name"] == "custom-model"
    assert llm.kwargs["temp"] == 0.7
    assert llm.kwargs["output_limit"] == 100


def test_skips_parameters_the_provider_does_not_accept(fake_module: Any) -> None:
    """If `timeout` isn't declared it must not be passed to the constructor."""
    spec = FAKE_SPEC.model_copy(deep=True)
    del spec.param_map["timeout"]
    llm = P.create_chat_model(config=fake_settings(spec))
    assert "deadline" not in llm.kwargs
    assert "timeout" not in llm.kwargs


# ---------------------------------------------------------------------------
# Error messages
# ---------------------------------------------------------------------------


def test_error_when_key_missing(fake_module: Any) -> None:
    with pytest.raises(P.LLMConfigError, match="GROQ_API_KEY"):
        P.create_chat_model(config=fake_settings(GROQ_API_KEY=""))


def test_error_when_provider_unknown() -> None:
    with pytest.raises(P.LLMConfigError, match="does-not-exist"):
        P.create_chat_model("does-not-exist", config=fake_settings())


def test_error_when_package_not_installed() -> None:
    spec = FAKE_SPEC.model_copy(update={"module": "package_that_never_existed"})
    with pytest.raises(P.LLMProviderNotInstalledError, match="pip install"):
        P.create_chat_model(config=fake_settings(spec))


def test_error_when_param_map_has_unknown_key(fake_module: Any) -> None:
    spec = FAKE_SPEC.model_copy(deep=True)
    spec.param_map["made_up_key"] = "whatever"
    with pytest.raises(P.LLMConfigError, match="made_up_key"):
        P.create_chat_model(config=fake_settings(spec))


# ---------------------------------------------------------------------------
# Default provider — inferred, no more LLM_PROVIDER variable
# ---------------------------------------------------------------------------


def _cfg(**keys: str) -> Settings:
    base = {"GROQ_API_KEY": "", "GOOGLE_API_KEY": ""}
    base.update(keys)
    return Settings(_env_file=None, **base)


def test_default_is_first_provider_with_a_key() -> None:
    assert _cfg(GOOGLE_API_KEY="k").llm_default_provider() == "google"
    assert _cfg(GROQ_API_KEY="k", GOOGLE_API_KEY="k").llm_default_provider() == "groq"


def test_no_keys_falls_back_to_first_provider() -> None:
    """So the error at model-call time names the missing key, instead of a vague error."""
    assert _cfg().llm_default_provider() == next(iter(C.DEFAULT_LLM_PROVIDERS))


def test_whitespace_only_key_does_not_count() -> None:
    assert _cfg(GROQ_API_KEY="   ", GOOGLE_API_KEY="k").llm_default_provider() == "google"


def test_legacy_llm_fields_are_no_longer_editable_on_web() -> None:
    """Provider/model are chosen in the chat panel — the Settings page must not
    show these four fields anymore, otherwise the two places would disagree."""
    for name in ("LLM_PROVIDER", "LLM_MODEL", "LLM_FAST_MODEL", "LLM_PROVIDERS"):
        assert name not in C.ALL_EDITABLE, name
        assert name not in Settings.model_fields, name


# ---------------------------------------------------------------------------
# Changing configuration at runtime (from the web UI)
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clean configuration state: doesn't read the machine's .env, doesn't leak between tests."""
    monkeypatch.setattr(C.Settings, "model_config", C.SettingsConfigDict(extra="ignore"))
    monkeypatch.setattr(C, "_base", None)
    monkeypatch.setattr(C, "_effective", None)
    monkeypatch.setattr(C, "_overrides", {})
    monkeypatch.setattr(C, "_store", C.MemoryOverrideStore())
    monkeypatch.setattr(C, "_callbacks", [])


def test_no_overrides_by_default(clean_config: None) -> None:
    assert C.runtime_overrides() == {}
    assert C.get_settings() is C.get_base_settings()


def test_change_values_from_ui(clean_config: None) -> None:
    C.apply_overrides({"LLM_TEMPERATURE": 0.9, "K8S_EXECUTION_MODE": "read_only"})

    cfg = C.get_settings()
    assert cfg.LLM_TEMPERATURE == 0.9
    assert cfg.K8S_EXECUTION_MODE == "read_only"
    # .env is left untouched
    assert C.get_base_settings().LLM_TEMPERATURE == 0.0


def test_proxy_sees_new_values(clean_config: None) -> None:
    """`from app.core.config import settings` must see new values immediately."""
    proxy = C.settings
    assert proxy.LLM_MAX_TOKENS == 4096

    C.apply_overrides({"LLM_MAX_TOKENS": 1234})

    assert proxy.LLM_MAX_TOKENS == 1234, "proxy still holds the old object"


def test_setting_none_restores_env_value(clean_config: None) -> None:
    C.apply_overrides({"LLM_TEMPERATURE": 0.9})
    assert C.get_settings().LLM_TEMPERATURE == 0.9

    C.apply_overrides({"LLM_TEMPERATURE": None})
    assert C.get_settings().LLM_TEMPERATURE == 0.0
    assert "LLM_TEMPERATURE" not in C.runtime_overrides()


def test_clear_all_overrides(clean_config: None) -> None:
    C.apply_overrides({"LLM_TEMPERATURE": 0.7, "LLM_MAX_TOKENS": 1000})
    C.clear_overrides()

    assert C.runtime_overrides() == {}
    assert C.get_settings().LLM_MAX_TOKENS == 4096


def test_rejects_non_editable_fields(clean_config: None) -> None:
    """Changing the DB connection string or JWT key at runtime is pointless/dangerous."""
    with pytest.raises(C.ConfigUpdateError, match="DATABASE_URL"):
        C.apply_overrides({"DATABASE_URL": "postgresql://attacker/"})

    with pytest.raises(C.ConfigUpdateError, match="JWT_SECRET"):
        C.apply_overrides({"JWT_SECRET": "hack"})


def test_invalid_value_rejects_whole_batch(clean_config: None) -> None:
    """One bad field cancels the whole batch; the running configuration stays as is."""
    C.apply_overrides({"LLM_TEMPERATURE": 0.5})

    with pytest.raises(C.ConfigUpdateError):
        C.apply_overrides(
            {
                "LLM_MAX_TOKENS": 8000,                  # valid
                "K8S_EXECUTION_MODE": "does-not-exist",  # invalid
            }
        )

    cfg = C.get_settings()
    assert cfg.LLM_TEMPERATURE == 0.5, "the old configuration must stay unchanged"
    assert cfg.LLM_MAX_TOKENS == 4096, "valid fields in a failed batch must NOT be applied"
    assert "LLM_MAX_TOKENS" not in C.runtime_overrides()


def test_secrets_are_redacted(clean_config: None) -> None:
    C.apply_overrides({"GROQ_API_KEY": "sk-real"})

    assert C.runtime_overrides()["GROQ_API_KEY"] == "***"
    assert C.runtime_overrides(redact_secrets=False)["GROQ_API_KEY"] == "sk-real"
    # The real value is still usable inside the system
    assert C.get_settings().GROQ_API_KEY == "sk-real"


def test_editable_fields_do_not_leak_secrets(clean_config: None) -> None:
    C.apply_overrides({"GROQ_API_KEY": "sk-real", "LLM_TEMPERATURE": 0.5})
    fields = {f["name"]: f for f in C.editable_fields()}

    key = fields["GROQ_API_KEY"]
    assert key["secret"] is True
    assert key["value"] is None, "the key value must not be returned to the UI"
    assert key["is_set"] is True

    temp = fields["LLM_TEMPERATURE"]
    assert temp["secret"] is False
    assert temp["value"] == 0.5
    assert temp["env_value"] == 0.0
    assert temp["overridden"] is True

    assert "DATABASE_URL" not in fields


def test_version_increments_on_every_change(clean_config: None) -> None:
    before = C.settings_version()
    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    assert C.settings_version() == before + 1


def test_callback_runs_on_change(clean_config: None) -> None:
    calls: list[int] = []
    C.on_reload(lambda: calls.append(1))

    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    C.clear_overrides()

    assert len(calls) == 2


def test_persisted_so_it_survives_restart(clean_config: None) -> None:
    """Changes made on the web are saved to the store and reloaded on the next startup."""
    store = C.MemoryOverrideStore()
    C.set_override_store(store)

    C.apply_overrides({"LLM_TEMPERATURE": 0.3})
    assert store.load() == {"LLM_TEMPERATURE": 0.3}

    # Simulate a restart: drop the current configuration, keep the store
    C._effective = None  # type: ignore[attr-defined]
    C._base = None  # type: ignore[attr-defined]
    C._overrides = {}  # type: ignore[attr-defined]

    assert C.get_settings().LLM_TEMPERATURE == 0.3


def test_ignores_corrupted_persisted_data(clean_config: None) -> None:
    """If the store holds garbage, run on plain .env instead of crashing at startup."""

    class BrokenStore:
        def load(self) -> dict[str, Any]:
            return {"K8S_EXECUTION_MODE": "garbage-value"}

        def save(self, values: dict[str, Any]) -> None: ...

    C._store = BrokenStore()  # type: ignore[attr-defined]
    C._effective = None  # type: ignore[attr-defined]

    cfg = C.get_settings()
    assert cfg.K8S_EXECUTION_MODE == "require_approval"
    assert C.runtime_overrides() == {}


def test_reload_from_env_keeps_web_changes(clean_config: None) -> None:
    """Re-reading .env must not wipe out what the user changed."""
    C.apply_overrides({"LLM_TEMPERATURE": 0.3})
    C.reload_from_env()

    assert C.get_settings().LLM_TEMPERATURE == 0.3
    assert C.runtime_overrides() == {"LLM_TEMPERATURE": 0.3}


# ---------------------------------------------------------------------------
# Model cache tied to configuration
# ---------------------------------------------------------------------------


def test_client_registers_cache_clearing() -> None:
    """client.py must register its cache-clearing function in config's callback list."""
    from app.integrations.llm import client

    assert client._clear_model_cache in C._callbacks, (
        "client.py forgot @on_reload — stale models will stay in the cache"
    )


def test_cache_cleared_when_config_changes(
    clean_config: None, fake_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Changing configuration on the web must leave the model cache EMPTY.

    Not checked by comparing model names: `settings_version()` is part of the
    cache key, so a new model gets built whether or not the callback runs — a
    test like that stays green even when cache clearing is broken.
    """
    from app.integrations.llm import client

    C.on_reload(client._clear_model_cache)  # the fixture wiped the callback list
    client._clear_model_cache()

    cfg = fake_settings()
    monkeypatch.setattr(client, "get_settings", lambda: cfg)

    client.get_llm()
    assert client.cache_size() == 1

    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    assert client.cache_size() == 0, "cache was not cleared when the configuration changed"


def test_model_is_reused_between_calls(fake_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two calls with the same parameters must return the same object."""
    from app.integrations.llm import client

    client._clear_model_cache()
    cfg = fake_settings()
    # client.py imports get_settings into its own namespace -> must patch it there
    monkeypatch.setattr(client, "get_settings", lambda: cfg)
    assert client.get_llm() is client.get_llm()


# ---------------------------------------------------------------------------
# Cross-check against the REAL library
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["groq", "google"])
def test_param_map_matches_real_class(name: str) -> None:
    """param_map must match the real parameter names of the LangChain class.

    The other tests use a fake module, so a wrong mapping still passes. This
    one loads the real library — skipped if that provider isn't installed.
    """
    from app.integrations.llm.provider import build_params, import_chat_class

    spec = C.DEFAULT_LLM_PROVIDERS[name]
    try:
        cls = import_chat_class(spec)
    except Exception:
        pytest.skip(f"{spec.package} not installed")

    valid = set(getattr(cls, "model_fields", {}) or {})
    valid |= {
        f.alias
        for f in (getattr(cls, "model_fields", {}) or {}).values()
        if getattr(f, "alias", None)
    }

    wrong = [real for real in spec.param_map.values() if real not in valid]
    assert not wrong, f"{spec.class_name} does not accept parameters: {wrong}"

    cfg = Settings(
        _env_file=None, GROQ_API_KEY="x", GOOGLE_API_KEY="x"
    )
    cls(**build_params(cfg, name))  # only building it for real proves it's right
