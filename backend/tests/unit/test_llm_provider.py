"""Kiểm tra lớp bọc nhà cung cấp LLM và cơ chế hot-reload cấu hình.

Không gọi mạng, không cần cài langchain-groq / langchain-google-genai:
dùng một module giả để soi phần ánh xạ tham số — đó mới là chỗ dễ sai.
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
# Nhà cung cấp giả
# ---------------------------------------------------------------------------


class FakeChatModel:
    """Ghi lại đúng những kwargs nhận được để bài test soi."""

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
    api_key_field="GROQ_API_KEY",  # mượn một field có sẵn trong Settings
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


def fake_settings(**kwargs: Any) -> Settings:
    """Settings dùng nhà cung cấp giả, không đọc .env của máy."""
    base: dict[str, Any] = {
        "_env_file": None,
        "LLM_PROVIDER": "fake",
        "LLM_PROVIDERS": {"fake": FAKE_SPEC},
        "GROQ_API_KEY": "sk-test",
    }
    base.update(kwargs)
    return Settings(**base)


# ---------------------------------------------------------------------------
# Đặc tả mặc định trong config.py
# ---------------------------------------------------------------------------


def test_co_du_ba_nha_cung_cap() -> None:
    assert {"groq", "google", "anthropic"} <= set(C.DEFAULT_LLM_PROVIDERS)


@pytest.mark.parametrize("name", ["groq", "google", "anthropic"])
def test_moi_nha_cung_cap_khai_bao_du(name: str) -> None:
    spec = C.DEFAULT_LLM_PROVIDERS[name]
    assert spec.model, f"{name} thiếu model mặc định"
    assert spec.fast_model, f"{name} thiếu model rẻ"
    assert spec.supports_tool_calling, f"{name} phải hỗ trợ gọi công cụ"
    # Thiếu ánh xạ thì tham số bị âm thầm bỏ qua — phải có đủ.
    assert set(spec.param_map) == set(C.CANONICAL_LLM_PARAMS), f"{name} ánh xạ thiếu"
    # Khoá API phải trỏ tới một field có thật trong Settings.
    assert spec.api_key_field in Settings.model_fields, f"{name} trỏ sai field khoá"


def test_ten_tham_so_khac_nhau_giua_cac_nha_cung_cap() -> None:
    """Đây chính là lý do cần lớp bọc — ba nhà đặt tên khác nhau."""
    d = C.DEFAULT_LLM_PROVIDERS
    assert d["groq"].param_map["max_tokens"] == "max_tokens"
    assert d["google"].param_map["max_tokens"] == "max_output_tokens"
    assert d["google"].param_map["api_key"] == "google_api_key"
    assert d["anthropic"].param_map["timeout"] == "default_request_timeout"


# ---------------------------------------------------------------------------
# Ánh xạ tham số
# ---------------------------------------------------------------------------


def test_doi_dung_ten_tham_so(fake_module: Any) -> None:
    llm = P.create_chat_model(config=fake_settings())
    assert llm.kwargs == {
        "secret": "sk-test",
        "model_name": "big-model",
        "temp": 0.0,
        "output_limit": 4096,
        "deadline": 60.0,
        "retries": 3,
        "vendor_flag": True,  # từ `extra`
    }


def test_ho_so_fast_doi_model(fake_module: Any) -> None:
    llm = P.create_chat_model(config=fake_settings(), profile="fast")
    assert llm.kwargs["model_name"] == "small-model"


def test_env_ghi_de_ten_model(fake_module: Any) -> None:
    """LLM_MODEL trong .env thắng model mặc định của nhà cung cấp."""
    llm = P.create_chat_model(config=fake_settings(LLM_MODEL="model-tu-env"))
    assert llm.kwargs["model_name"] == "model-tu-env"


def test_tham_so_truyen_tay_thang_settings(fake_module: Any) -> None:
    llm = P.create_chat_model(
        config=fake_settings(LLM_TEMPERATURE=0.1),
        model="model-tuy-chon",
        temperature=0.7,
        max_tokens=100,
    )
    assert llm.kwargs["model_name"] == "model-tuy-chon"
    assert llm.kwargs["temp"] == 0.7
    assert llm.kwargs["output_limit"] == 100


def test_bo_qua_tham_so_nha_cung_cap_khong_nhan(fake_module: Any) -> None:
    """Không khai báo `timeout` thì không được truyền vào constructor."""
    spec = FAKE_SPEC.model_copy(deep=True)
    del spec.param_map["timeout"]
    llm = P.create_chat_model(config=fake_settings(LLM_PROVIDERS={"fake": spec}))
    assert "deadline" not in llm.kwargs
    assert "timeout" not in llm.kwargs


# ---------------------------------------------------------------------------
# Thông báo lỗi
# ---------------------------------------------------------------------------


def test_bao_loi_khi_thieu_khoa(fake_module: Any) -> None:
    with pytest.raises(P.LLMConfigError, match="GROQ_API_KEY"):
        P.create_chat_model(config=fake_settings(GROQ_API_KEY=""))


def test_bao_loi_khi_khong_co_nha_cung_cap() -> None:
    with pytest.raises(P.LLMConfigError, match="khong-ton-tai"):
        P.create_chat_model("khong-ton-tai", config=fake_settings())


def test_bao_loi_khi_chua_cai_goi() -> None:
    spec = FAKE_SPEC.model_copy(update={"module": "goi_chua_bao_gio_ton_tai"})
    with pytest.raises(P.LLMProviderNotInstalled, match="uv pip install"):
        P.create_chat_model(config=fake_settings(LLM_PROVIDERS={"fake": spec}))


def test_bao_loi_khi_param_map_co_khoa_la(fake_module: Any) -> None:
    spec = FAKE_SPEC.model_copy(deep=True)
    spec.param_map["khoa_bia_dat"] = "gi_do"
    with pytest.raises(P.LLMConfigError, match="khoa_bia_dat"):
        P.create_chat_model(config=fake_settings(LLM_PROVIDERS={"fake": spec}))


# ---------------------------------------------------------------------------
# Ghi đè từng phần qua .env
# ---------------------------------------------------------------------------


def test_ghi_de_tung_phan_giu_nguyen_truong_khac() -> None:
    """Chỉ ghi `model` thì các trường còn lại phải giữ nguyên mặc định."""
    cfg = Settings(_env_file=None, LLM_PROVIDERS={"groq": {"model": "model-khac"}})
    groq = cfg.llm_provider("groq")
    assert groq.model == "model-khac"
    assert groq.module == "langchain_groq"           # giữ nguyên
    assert groq.param_map["timeout"] == "request_timeout"  # giữ nguyên
    # Nhà cung cấp khác không bị ảnh hưởng
    assert "google" in cfg.LLM_PROVIDERS
    assert cfg.llm_provider("anthropic").model == "claude-sonnet-5"


def test_them_nha_cung_cap_moi_khong_sua_code() -> None:
    """Thêm hẳn nhà cung cấp mới chỉ bằng cấu hình."""
    cfg = Settings(
        _env_file=None,
        LLM_PROVIDERS={
            "openai": {
                "package": "langchain-openai",
                "module": "langchain_openai",
                "class_name": "ChatOpenAI",
                "api_key_field": "GROQ_API_KEY",
                "model": "gpt-4o",
                "param_map": {"api_key": "api_key", "model": "model"},
            }
        },
    )
    assert cfg.llm_provider("openai").model == "gpt-4o"
    assert "groq" in cfg.LLM_PROVIDERS  # mặc định vẫn còn




# ---------------------------------------------------------------------------
# Đổi cấu hình lúc chạy (từ giao diện web)
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Trạng thái cấu hình sạch, không đọc .env của máy, không dính bài test khác."""
    monkeypatch.setattr(C.Settings, "model_config", C.SettingsConfigDict(extra="ignore"))
    monkeypatch.setattr(C, "_base", None)
    monkeypatch.setattr(C, "_effective", None)
    monkeypatch.setattr(C, "_overrides", {})
    monkeypatch.setattr(C, "_store", C.MemoryOverrideStore())
    monkeypatch.setattr(C, "_callbacks", [])


def test_mac_dinh_khong_co_ghi_de(clean_config: None) -> None:
    assert C.runtime_overrides() == {}
    assert C.get_settings() is C.get_base_settings()


def test_doi_gia_tri_tu_giao_dien(clean_config: None) -> None:
    C.apply_overrides({"LLM_TEMPERATURE": 0.9, "LLM_PROVIDER": "google"})

    cfg = C.get_settings()
    assert cfg.LLM_TEMPERATURE == 0.9
    assert cfg.LLM_PROVIDER == "google"
    # .env không bị động tới
    assert C.get_base_settings().LLM_TEMPERATURE == 0.0


def test_proxy_thay_gia_tri_moi(clean_config: None) -> None:
    """`from app.core.config import settings` phải thấy giá trị mới ngay."""
    proxy = C.settings
    assert proxy.LLM_PROVIDER == "groq"

    C.apply_overrides({"LLM_PROVIDER": "anthropic"})

    assert proxy.LLM_PROVIDER == "anthropic", "proxy vẫn cầm object cũ"


def test_dat_none_de_tra_ve_gia_tri_env(clean_config: None) -> None:
    C.apply_overrides({"LLM_TEMPERATURE": 0.9})
    assert C.get_settings().LLM_TEMPERATURE == 0.9

    C.apply_overrides({"LLM_TEMPERATURE": None})
    assert C.get_settings().LLM_TEMPERATURE == 0.0
    assert "LLM_TEMPERATURE" not in C.runtime_overrides()


def test_xoa_het_ghi_de(clean_config: None) -> None:
    C.apply_overrides({"LLM_PROVIDER": "google", "LLM_MAX_TOKENS": 1000})
    C.clear_overrides()

    assert C.runtime_overrides() == {}
    assert C.get_settings().LLM_PROVIDER == "groq"


def test_chan_truong_khong_duoc_phep_doi(clean_config: None) -> None:
    """Đổi chuỗi kết nối CSDL hay khoá JWT lúc chạy là vô nghĩa/nguy hiểm."""
    with pytest.raises(C.ConfigUpdateError, match="DATABASE_URL"):
        C.apply_overrides({"DATABASE_URL": "postgresql://ke-tan-cong/"})

    with pytest.raises(C.ConfigUpdateError, match="JWT_SECRET"):
        C.apply_overrides({"JWT_SECRET": "hack"})


def test_gia_tri_sai_bi_tu_choi_va_khong_ap_dung_gi(clean_config: None) -> None:
    """Sai một trường thì cả lô bị huỷ, cấu hình đang chạy giữ nguyên."""
    C.apply_overrides({"LLM_PROVIDER": "google"})

    with pytest.raises(C.ConfigUpdateError):
        C.apply_overrides(
            {
                "LLM_MAX_TOKENS": 8000,                 # hợp lệ
                "K8S_EXECUTION_MODE": "khong-ton-tai",  # sai
            }
        )

    cfg = C.get_settings()
    assert cfg.LLM_PROVIDER == "google", "cấu hình cũ phải giữ nguyên"
    assert cfg.LLM_MAX_TOKENS == 4096, "trường hợp lệ trong lô hỏng KHÔNG được áp"
    assert "LLM_MAX_TOKENS" not in C.runtime_overrides()


def test_che_giau_khoa_bi_mat(clean_config: None) -> None:
    C.apply_overrides({"GROQ_API_KEY": "sk-that"})

    assert C.runtime_overrides()["GROQ_API_KEY"] == "***"
    assert C.runtime_overrides(redact_secrets=False)["GROQ_API_KEY"] == "sk-that"
    # Giá trị thật vẫn dùng được ở trong hệ thống
    assert C.get_settings().GROQ_API_KEY == "sk-that"


def test_editable_fields_khong_lo_khoa_bi_mat(clean_config: None) -> None:
    C.apply_overrides({"GROQ_API_KEY": "sk-that", "LLM_TEMPERATURE": 0.5})
    fields = {f["name"]: f for f in C.editable_fields()}

    khoa = fields["GROQ_API_KEY"]
    assert khoa["secret"] is True
    assert khoa["value"] is None, "không được trả giá trị khoá ra giao diện"
    assert khoa["is_set"] is True

    temp = fields["LLM_TEMPERATURE"]
    assert temp["secret"] is False
    assert temp["value"] == 0.5
    assert temp["env_value"] == 0.0
    assert temp["overridden"] is True

    assert "DATABASE_URL" not in fields


def test_ghi_de_llm_providers_tung_phan(clean_config: None) -> None:
    """Đổi model của groq từ giao diện không được xoá các trường khác."""
    C.apply_overrides({"LLM_PROVIDERS": {"groq": {"model": "model-tu-web"}}})

    groq = C.get_settings().llm_provider("groq")
    assert groq.model == "model-tu-web"
    assert groq.module == "langchain_groq"                  # giữ nguyên
    assert groq.param_map["timeout"] == "request_timeout"   # giữ nguyên
    assert C.get_settings().llm_provider("google").model == "gemini-2.5-flash"


def test_version_tang_sau_moi_lan_doi(clean_config: None) -> None:
    truoc = C.settings_version()
    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    assert C.settings_version() == truoc + 1


def test_callback_duoc_goi_khi_doi(clean_config: None) -> None:
    goi: list[int] = []
    C.on_reload(lambda: goi.append(1))

    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    C.clear_overrides()

    assert len(goi) == 2


def test_luu_lai_de_khoi_dong_lai_van_con(clean_config: None) -> None:
    """Phần đổi trên web được cất vào store và nạp lại ở lần khởi động sau."""
    store = C.MemoryOverrideStore()
    C.set_override_store(store)

    C.apply_overrides({"LLM_PROVIDER": "anthropic"})
    assert store.load() == {"LLM_PROVIDER": "anthropic"}

    # Giả lập khởi động lại: xoá cấu hình đang có, giữ nguyên store
    C._effective = None  # type: ignore[attr-defined]
    C._base = None  # type: ignore[attr-defined]
    C._overrides = {}  # type: ignore[attr-defined]

    assert C.get_settings().LLM_PROVIDER == "anthropic"


def test_bo_qua_du_lieu_luu_bi_hong(clean_config: None) -> None:
    """Store chứa giá trị rác thì chạy bằng .env thuần, không sập lúc khởi động."""

    class BrokenStore:
        def load(self) -> dict[str, Any]:
            return {"K8S_EXECUTION_MODE": "gia-tri-rac"}

        def save(self, values: dict[str, Any]) -> None: ...

    C._store = BrokenStore()  # type: ignore[attr-defined]
    C._effective = None  # type: ignore[attr-defined]

    cfg = C.get_settings()
    assert cfg.K8S_EXECUTION_MODE == "require_approval"
    assert C.runtime_overrides() == {}


def test_reload_from_env_giu_phan_doi_tren_web(clean_config: None) -> None:
    """Đọc lại .env không được thổi bay thứ người dùng đã đổi."""
    C.apply_overrides({"LLM_PROVIDER": "google"})
    C.reload_from_env()

    assert C.get_settings().LLM_PROVIDER == "google"
    assert C.runtime_overrides() == {"LLM_PROVIDER": "google"}


# ---------------------------------------------------------------------------
# Bộ nhớ đệm model theo cấu hình
# ---------------------------------------------------------------------------


def test_client_dang_ky_don_dem() -> None:
    """client.py phải đăng ký hàm dọn đệm vào danh sách callback của config."""
    from app.integrations.llm import client

    assert client._clear_model_cache in C._callbacks, (
        "client.py quên gắn @on_reload — model cũ sẽ nằm lại trong bộ nhớ đệm"
    )


def test_dem_bi_xoa_khi_doi_cau_hinh(
    clean_config: None, fake_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Đổi cấu hình trên web thì bộ nhớ đệm model phải RỖNG.

    Không kiểm bằng cách so tên model: `settings_version()` nằm trong khoá đệm
    nên model mới vẫn được dựng dù callback có chạy hay không — bài test kiểu
    đó xanh cả khi cơ chế dọn đệm đã hỏng.
    """
    from app.integrations.llm import client

    C.on_reload(client._clear_model_cache)  # fixture đã xoá danh sách callback
    client._clear_model_cache()

    cfg = fake_settings()
    monkeypatch.setattr(client, "get_settings", lambda: cfg)

    client.get_llm()
    assert client.cache_size() == 1

    C.apply_overrides({"LLM_MAX_TOKENS": 2048})
    assert client.cache_size() == 0, "đệm không được dọn khi cấu hình đổi"


def test_dem_lai_model_giua_hai_lan_goi(fake_module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Gọi hai lần cùng tham số phải trả về cùng một đối tượng."""
    from app.integrations.llm import client

    client._clear_model_cache()
    cfg = fake_settings()
    # client.py import get_settings vào namespace riêng -> phải vá ở đó
    monkeypatch.setattr(client, "get_settings", lambda: cfg)
    assert client.get_llm() is client.get_llm()


# ---------------------------------------------------------------------------
# Đối chiếu với thư viện THẬT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ten", ["groq", "google", "anthropic"])
def test_param_map_khop_voi_class_that(ten: str) -> None:
    """param_map phải trùng tên tham số thật của class LangChain.

    Các bài test khác dùng module giả nên ánh xạ sai vẫn xanh. Bài này nạp
    thư viện thật — bỏ qua nếu nhà cung cấp đó chưa được cài.
    """
    from app.integrations.llm.provider import build_params, import_chat_class

    spec = C.DEFAULT_LLM_PROVIDERS[ten]
    try:
        cls = import_chat_class(spec)
    except Exception:
        pytest.skip(f"chưa cài {spec.package}")

    hop_le = set(getattr(cls, "model_fields", {}) or {})
    hop_le |= {
        f.alias
        for f in (getattr(cls, "model_fields", {}) or {}).values()
        if getattr(f, "alias", None)
    }

    sai = [thuc for thuc in spec.param_map.values() if thuc not in hop_le]
    assert not sai, f"{spec.class_name} không nhận tham số: {sai}"

    cfg = Settings(
        _env_file=None, GROQ_API_KEY="x", GOOGLE_API_KEY="x", ANTHROPIC_API_KEY="x"
    )
    cls(**build_params(cfg, ten))  # dựng được thật thì mới chắc chắn đúng
