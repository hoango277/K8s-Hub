"""Kiểm tra phần đặt tiêu đề và nạp lại lịch sử làm ngữ cảnh.

Không đụng cơ sở dữ liệu: dùng đối tượng giả có đúng các thuộc tính mà hàm
cần đọc.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.db.models.thread import TITLE_MAX
from app.modules.nl_command.agent import history_to_messages
from app.services.thread_service import DEFAULT_TITLE, title_from


@dataclass
class TinNhanGia:
    role: str
    content: str
    status: str = "complete"


# --------------------------------------------------------------------------
# Tiêu đề
# --------------------------------------------------------------------------


def test_tieu_de_lay_tu_cau_hoi():
    assert title_from("Scale deployment api lên 3") == "Scale deployment api lên 3"


def test_tieu_de_gom_khoang_trang_thua():
    assert title_from("  pod   api   lỗi\n\nvì sao  ") == "pod api lỗi vì sao"


def test_tieu_de_rong_dung_mac_dinh():
    assert title_from("   \n  ") == DEFAULT_TITLE


def test_tieu_de_dai_bi_cat_vua_cot_csdl():
    """Cắt hụt một ký tự thì câu lệnh INSERT sẽ vỡ vì vượt quá VARCHAR."""
    tieu_de = title_from("a" * 500)

    assert len(tieu_de) <= TITLE_MAX
    assert tieu_de.endswith("…")


def test_tieu_de_dung_do_dai_gioi_han_khong_bi_cat():
    nguyen_ven = "b" * TITLE_MAX
    assert title_from(nguyen_ven) == nguyen_ven


# --------------------------------------------------------------------------
# Lịch sử -> tin nhắn cho mô hình
# --------------------------------------------------------------------------


def test_giu_dung_thu_tu_va_dung_vai():
    messages = history_to_messages(
        [
            TinNhanGia("user", "pod api sao thế"),
            TinNhanGia("assistant", "Đang kiểm tra"),
            TinNhanGia("user", "còn gì nữa không"),
        ]
    )

    assert [type(m) for m in messages] == [HumanMessage, AIMessage, HumanMessage]
    assert [m.content for m in messages] == [
        "pod api sao thế",
        "Đang kiểm tra",
        "còn gì nữa không",
    ]


def test_bo_tin_nhan_rong():
    """Bản ghi của trợ lý được tạo TRƯỚC khi nó nói, nên lúc nạp lại lịch sử
    cho chính lượt đó, nội dung còn rỗng. Gửi tin nhắn rỗng lên thì vài nhà
    cung cấp trả lỗi."""
    messages = history_to_messages(
        [TinNhanGia("user", "hỏi"), TinNhanGia("assistant", "", status="streaming")]
    )

    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)


@pytest.mark.parametrize("trang_thai", ["streaming", "error"])
def test_bo_cau_tra_loi_chua_hoan_chinh(trang_thai: str):
    """Câu trả lời dở dang không được đưa lại làm ngữ cảnh — mô hình sẽ tưởng
    đó là điều nó đã nói xong và nói tiếp từ giữa chừng."""
    messages = history_to_messages(
        [TinNhanGia("assistant", "Tôi đang xem thì", status=trang_thai)]
    )

    assert messages == []


def test_bo_vai_he_thong():
    """Lời nhắc hệ thống được ghép lúc chạy, không lấy từ lịch sử — nếu không
    sẽ có hai bản chồng nhau."""
    messages = history_to_messages([TinNhanGia("system", "bạn là trợ lý")])

    assert messages == []
