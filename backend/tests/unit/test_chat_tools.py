"""Kiểm tra các công cụ trợ lý được phép gọi.

Trước khi có file này, không test nào THỰC SỰ gọi công cụ — chúng chỉ được
kiểm gián tiếp qua luồng sự kiện giả. Hậu quả: một lần sửa làm `system_info`
đọc nhầm tham số `config` (là RunnableConfig, không phải Settings) vẫn qua được
toàn bộ bộ test, và chỉ nổ khi người dùng hỏi thật.
"""

from __future__ import annotations

import pytest

from app.modules.nl_command.tools import CHAT_TOOLS, current_time, get_tools, system_info


def goi(cong_cu, metadata: dict | None = None) -> str:
    """Gọi công cụ đúng cách LangGraph gọi nó."""
    return cong_cu.invoke({}, config={"metadata": metadata or {}})


# --------------------------------------------------------------------------
# Chạy được thật
# --------------------------------------------------------------------------


@pytest.mark.parametrize("cong_cu", CHAT_TOOLS, ids=lambda t: t.name)
def test_moi_cong_cu_chay_duoc(cong_cu):
    """Gọi thật từng công cụ. Bắt lỗi kiểu 'đọc nhầm thuộc tính' ngay tại đây."""
    ket_qua = goi(cong_cu)

    assert isinstance(ket_qua, str)
    assert ket_qua.strip()


def test_khong_loi_khi_thieu_metadata():
    """LangGraph có thể gọi mà không kèm metadata nào."""
    assert system_info.invoke({}).strip()


# --------------------------------------------------------------------------
# system_info phải khai đúng model ĐANG chạy
# --------------------------------------------------------------------------


def test_bao_dung_model_cua_luot_nay():
    """Người dùng chọn model riêng cho một lượt thì công cụ phải khai đúng nó.

    Đọc cấu hình chung thì trợ lý tự khai sai về chính nó ngay sau khi người
    dùng đổi model trên giao diện.
    """
    ket_qua = goi(
        system_info,
        {"llm_provider": "google", "llm_model": "gemini-2.5-flash"},
    )

    assert "google / gemini-2.5-flash" in ket_qua


def test_thieu_lua_chon_thi_lay_cau_hinh_chung():
    from app.core.config import get_settings

    cfg = get_settings()
    ket_qua = goi(system_info)

    assert f"{cfg.LLM_PROVIDER} / {cfg.llm_model_name()}" in ket_qua


def test_co_du_thong_tin_van_hanh():
    """Công cụ này tồn tại để trả lời 'hệ thống đang ở chế độ nào'."""
    ket_qua = goi(system_info)

    for phan in ("Mô hình AI:", "Chế độ thực thi:", "Namespace được phép:"):
        assert phan in ket_qua


# --------------------------------------------------------------------------
# Tham số `config` không được lộ ra cho mô hình
# --------------------------------------------------------------------------


def test_mo_hinh_khong_nhin_thay_tham_so_config():
    """`config` do LangChain tiêm vào, không phải thứ mô hình điền.

    Lọt vào schema thì mô hình sẽ cố sinh ra một object RunnableConfig — vừa
    tốn token vừa dễ gọi sai.
    """
    truong = system_info.args_schema.model_json_schema().get("properties", {})

    assert "config" not in truong


@pytest.mark.parametrize("cong_cu", CHAT_TOOLS, ids=lambda t: t.name)
def test_co_mo_ta_cho_mo_hinh_doc(cong_cu):
    """Mô tả là thứ mô hình dựa vào để quyết định gọi hay không."""
    assert (cong_cu.description or "").strip()


# --------------------------------------------------------------------------
# Ranh giới an toàn
# --------------------------------------------------------------------------


def test_khong_cong_cu_nao_nhan_chuoi_lenh_tho():
    """Không được có công cụ kiểu `run_kubectl(cmd)`.

    Tham số phải là trường rời rạc để kiểm tra được trước khi chạy. Nhận chuỗi
    lệnh thô là mở đường cho mô hình tự chế lệnh tuỳ ý.
    """
    ngo_vuc = {"cmd", "command", "shell", "script", "kubectl", "query_raw"}

    for cong_cu in CHAT_TOOLS:
        truong = set(cong_cu.args_schema.model_json_schema().get("properties", {}))
        assert not (truong & ngo_vuc), f"{cong_cu.name} nhận tham số nguy hiểm: {truong}"


def test_get_tools_tra_ban_sao():
    """Nơi gọi thêm/bớt công cụ không được làm hỏng danh sách gốc."""
    ds = get_tools()
    ds.clear()

    assert len(get_tools()) == len(CHAT_TOOLS) > 0


def test_current_time_tra_ve_gio_utc():
    assert "UTC" in goi(current_time)
