"""Kiểm tra lớp phiên dịch sự kiện LangGraph -> SSE.

Đây là chỗ dễ hỏng nhất khi nâng phiên bản LangGraph: tên sự kiện đổi, hình
dạng `data` đổi, và hỏng thì KHÔNG có ngoại lệ nào — khung chat chỉ lặng lẽ
không hiện gì. Test ở đây dựng sẵn luồng sự kiện giả để bắt được chuyện đó mà
không cần gọi mô hình thật.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from app.integrations.llm.streaming import (
    StreamCollector,
    _reasoning_of,
    _text_of,
    stream_graph_events,
)
from app.schemas.events import EventStream


class DoThiGia:
    """Đồ thị giả, phát ra đúng danh sách sự kiện được đưa vào."""

    def __init__(self, events: list[dict[str, Any]], loi: Exception | None = None):
        self._events = events
        self._loi = loi

    async def astream_events(self, state, config=None, version="v2"):  # noqa: ARG002
        for e in self._events:
            yield e
        if self._loi is not None:
            raise self._loi


def token(text: str) -> dict[str, Any]:
    return {
        "event": "on_chat_model_stream",
        "name": "model",
        "run_id": "r1",
        "data": {"chunk": AIMessageChunk(content=text)},
    }


def tool_start(run_id: str, name: str, args: dict) -> dict[str, Any]:
    return {
        "event": "on_tool_start",
        "name": name,
        "run_id": run_id,
        "data": {"input": args},
    }


def tool_end(run_id: str, content: str, status: str = "success") -> dict[str, Any]:
    return {
        "event": "on_tool_end",
        "name": "tool",
        "run_id": run_id,
        "data": {
            "output": ToolMessage(content=content, tool_call_id=run_id, status=status)
        },
    }


async def chay(events, loi=None) -> tuple[list[dict], StreamCollector]:
    stream = EventStream()
    collector = StreamCollector()
    khung = [
        f
        async for f in stream_graph_events(
            DoThiGia(events, loi), {"messages": []}, stream=stream, collector=collector
        )
    ]
    return khung, collector


def loai(khung: list[dict]) -> list[str]:
    return [k["event"] for k in khung]


def du_lieu(khung: dict) -> dict:
    return json.loads(khung["data"])


# --------------------------------------------------------------------------


async def test_token_duoc_noi_lai_dung_thu_tu():
    khung, collector = await chay([token("Xin"), token(" chào"), token(" bạn")])

    assert loai(khung) == ["token", "token", "token"]
    assert [du_lieu(k)["content"] for k in khung] == ["Xin", " chào", " bạn"]
    assert collector.content == "Xin chào bạn"


async def test_seq_tang_dan_tu_1():
    khung, _ = await chay([token("a"), token("b"), token("c")])

    assert [du_lieu(k)["seq"] for k in khung] == [1, 2, 3]
    # `id` của khung SSE phải trùng seq để client resume được sau khi mất kết nối.
    assert [k["id"] for k in khung] == ["1", "2", "3"]


async def test_token_rong_khong_duoc_gui():
    """Mô hình hay nhả chunk rỗng khi đang dựng yêu cầu gọi công cụ."""
    khung, collector = await chay([token(""), token("a"), token("")])

    assert loai(khung) == ["token"]
    assert collector.content == "a"


async def test_goi_cong_cu_ghep_dung_cap():
    khung, collector = await chay(
        [
            tool_start("abc", "list_pods", {"namespace": "default"}),
            tool_end("abc", "3 pods"),
        ]
    )

    assert loai(khung) == ["tool_call_start", "tool_call_end"]

    dau, cuoi = du_lieu(khung[0]), du_lieu(khung[1])
    assert dau["id"] == cuoi["id"] == "abc"
    assert dau["name"] == "list_pods"
    assert dau["args"] == {"namespace": "default"}
    assert cuoi["status"] == "ok"
    assert cuoi["result"] == "3 pods"
    assert cuoi["duration_ms"] >= 0

    assert len(collector.tool_calls) == 1
    assert collector.tool_calls[0].status == "ok"


async def test_cong_cu_loi_duoc_danh_dau_loi():
    """ToolNode nuốt ngoại lệ và trả ToolMessage status='error'.

    Không nhận ra qua trường đó thì lỗi công cụ sẽ bị hiển thị như kết quả bình
    thường — người dùng tưởng tra cứu thành công.
    """
    khung, collector = await chay(
        [tool_start("x", "get_logs", {}), tool_end("x", "pod không tồn tại", "error")]
    )

    cuoi = du_lieu(khung[1])
    assert cuoi["status"] == "error"
    assert cuoi["error"] == "pod không tồn tại"
    assert "result" not in cuoi  # exclude_none: không gửi trường rỗng

    assert collector.tool_calls[0].status == "error"
    assert collector.tool_calls[0].result is None


async def test_nhieu_cong_cu_chay_long_nhau():
    khung, _ = await chay(
        [
            tool_start("a", "t1", {}),
            tool_start("b", "t2", {}),
            tool_end("b", "xong b"),
            tool_end("a", "xong a"),
        ]
    )

    ket_qua = {du_lieu(k)["id"]: du_lieu(k).get("result") for k in khung[2:]}
    assert ket_qua == {"b": "xong b", "a": "xong a"}


async def test_cong_cu_khong_bao_gio_ket_thuc_bi_danh_dau_loi():
    """Luồng đứt khi công cụ chưa trả kết quả — không được để nó treo mãi ở
    trạng thái 'đang chạy' trong cơ sở dữ liệu."""
    _, collector = await chay([tool_start("a", "t1", {})])

    assert collector.tool_calls[0].status == "error"
    assert collector.tool_calls[0].duration_ms is not None


async def test_ket_thuc_khong_cap_bi_bo_qua():
    khung, collector = await chay([tool_end("la", "kết quả trời ơi")])

    assert khung == []
    assert collector.tool_calls == []


async def test_loi_giua_chung_thanh_su_kien_error():
    khung, collector = await chay([token("a")], loi=RuntimeError("nổ"))

    assert loai(khung) == ["token", "error"]
    assert du_lieu(khung[1])["code"] == "agent_error"
    assert collector.error is not None
    # Phần đã nói trước khi lỗi vẫn phải giữ lại để lưu.
    assert collector.content == "a"


@pytest.mark.parametrize(
    ("loi", "ma", "thu_lai"),
    [
        (TimeoutError("quá lâu"), "llm_timeout", True),
        (RuntimeError("rate limit exceeded (429)"), "llm_rate_limit", True),
        (RuntimeError("invalid api key"), "llm_auth", False),
        (RuntimeError("chuyện gì đó"), "agent_error", False),
    ],
)
async def test_phan_loai_loi(loi: Exception, ma: str, thu_lai: bool):
    khung, _ = await chay([], loi=loi)

    d = du_lieu(khung[0])
    assert d["code"] == ma
    assert d["retryable"] is thu_lai


async def test_cong_don_token_qua_nhieu_lan_goi_mo_hinh():
    """Một lượt có gọi công cụ sẽ gọi mô hình nhiều lần; số token phải cộng dồn."""

    def ket_thuc(vao: int, ra: int) -> dict[str, Any]:
        msg = AIMessage(content="x")
        msg.usage_metadata = {
            "input_tokens": vao,
            "output_tokens": ra,
            "total_tokens": vao + ra,
        }
        return {"event": "on_chat_model_end", "name": "m", "run_id": "r", "data": {"output": msg}}

    _, collector = await chay([ket_thuc(100, 20), ket_thuc(300, 50)])

    assert collector.prompt_tokens == 400
    assert collector.completion_tokens == 70


# --------------------------------------------------------------------------
# Bóc chữ từ nội dung tin nhắn
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("vao", "ra"),
    [
        ("chuỗi thường", "chuỗi thường"),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        # Khối suy luận và khối gọi công cụ không phải chữ trả lời cho người dùng.
        ([{"type": "thinking", "thinking": "ngẫm"}, {"type": "text", "text": "ra"}], "ra"),
        ([{"type": "tool_use", "name": "t", "input": {}}], ""),
        ([], ""),
        (None, ""),
    ],
)
def test_text_of(vao, ra):
    assert _text_of(vao) == ra


# --------------------------------------------------------------------------
# Suy luận (thinking)
# --------------------------------------------------------------------------


def thinking(text: str) -> dict[str, Any]:
    """Mẩu suy luận kiểu Groq: nằm ở additional_kwargs."""
    ch = AIMessageChunk(content="")
    ch.additional_kwargs = {"reasoning_content": text}
    return {
        "event": "on_chat_model_stream",
        "name": "model",
        "run_id": "r1",
        "data": {"chunk": ch},
    }


async def test_suy_luan_thanh_su_kien_rieng():
    khung, collector = await chay([thinking("Cần tra "), thinking("giờ trước.")])

    assert loai(khung) == ["thinking", "thinking"]
    assert collector.reasoning == "Cần tra giờ trước."
    # Suy luận KHÔNG được tính là câu trả lời.
    assert collector.content == ""


async def test_suy_luan_va_cau_tra_loi_khong_tron_vao_nhau():
    khung, collector = await chay(
        [thinking("Người dùng hỏi giờ."), token("Bây giờ là 7h.")]
    )

    assert loai(khung) == ["thinking", "token"]
    assert collector.reasoning == "Người dùng hỏi giờ."
    assert collector.content == "Bây giờ là 7h."


async def test_giu_lai_suy_luan_khi_luong_loi_giua_chung():
    _, collector = await chay([thinking("đang nghĩ dở")], loi=RuntimeError("nổ"))

    assert collector.reasoning == "đang nghĩ dở"


@pytest.mark.parametrize(
    ("noi_dung", "mong_doi"),
    [
        # Anthropic: khối thinking trong content.
        ([{"type": "thinking", "thinking": "hãy xem log"}], "hãy xem log"),
        # Google Gemini: vẫn type='text' nhưng có cờ thought.
        ([{"type": "text", "text": "ngẫm đã", "thought": True}], "ngẫm đã"),
        # Khối chữ bình thường thì KHÔNG phải suy luận.
        ([{"type": "text", "text": "câu trả lời"}], ""),
    ],
)
def test_reasoning_of_theo_tung_nha_cung_cap(noi_dung, mong_doi):
    ch = AIMessageChunk(content=noi_dung)
    assert _reasoning_of(ch) == mong_doi


def test_khoi_thought_khong_lot_vao_cau_tra_loi():
    """Gemini đánh dấu suy luận bằng cờ `thought` nhưng vẫn để type='text'.

    Bỏ sót cờ đó là suy luận chảy thẳng vào câu trả lời của người dùng.
    """
    noi_dung = [
        {"type": "text", "text": "nghĩ thầm", "thought": True},
        {"type": "text", "text": "nói ra"},
    ]
    assert _text_of(noi_dung) == "nói ra"
