"""Dịch sự kiện của LangGraph sang sự kiện gửi cho trình duyệt.

LangGraph phát ra một luồng sự kiện rất chi tiết (`astream_events`) mô tả mọi
thứ đang xảy ra bên trong: mô hình đang nhả chữ, một công cụ bắt đầu chạy, một
công cụ vừa xong… Nhưng đó là ngôn ngữ nội bộ của thư viện, không phải thứ nên
để lọt ra ngoài — nó đổi theo phiên bản, và chứa nhiều thông tin thừa.

File này là lớp phiên dịch duy nhất giữa hai thế giới đó. Bên trong là sự kiện
của LangGraph, bên ngoài là `app/schemas/events.py` — hợp đồng cố định với
frontend. Đổi phiên bản LangGraph thì chỉ file này phải sửa.

Ngoài việc phát sự kiện, nó còn GOM LẠI kết quả cuối cùng (toàn bộ câu trả lời,
các lần gọi công cụ, số token) vào `StreamCollector` để tầng gọi ghi vào CSDL —
tránh phải nghe lại luồng lần thứ hai.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.schemas.events import (
    ErrorEvent,
    EventStream,
    ThinkingEvent,
    TokenEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

logger = logging.getLogger(__name__)

# Kết quả công cụ gửi xuống trình duyệt bị cắt bớt: log một pod có thể vài trăm
# nghìn ký tự, đẩy hết xuống thì treo trình duyệt. Bản đầy đủ vẫn đi vào
# Langfuse và vẫn được mô hình nhìn thấy — chỗ này chỉ là phần để HIỂN THỊ.
RESULT_DISPLAY_MAX = 2000


@dataclass
class ToolCallRecord:
    """Một lần gọi công cụ, gom đủ để ghi vào CSDL."""

    call_id: str
    name: str
    args: dict[str, Any]
    started_at: datetime
    result: str | None = None
    status: str = "running"
    error: str | None = None
    duration_ms: int | None = None

    # Dùng để tính thời lượng; đồng hồ hệ thống có thể bị chỉnh nên không lấy
    # hiệu của hai mốc datetime.
    _bat_dau: float = field(default_factory=time.perf_counter, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "name": self.name,
            "args": self.args,
            "result": self.result,
            "status": self.status,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
        }


@dataclass
class StreamCollector:
    """Những gì đọng lại sau khi luồng chạy xong."""

    content: str = ""

    # Phần mô hình tự nghĩ. Rỗng khi nhà cung cấp không lộ suy luận.
    reasoning: str = ""

    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None

    def tool_calls_as_dicts(self) -> list[dict[str, Any]]:
        return [tc.to_dict() for tc in self.tool_calls]


def _text_of(content: Any) -> str:
    """Lấy phần chữ TRẢ LỜI từ nội dung tin nhắn.

    Mỗi nhà cung cấp trả một dạng khác nhau: Groq trả chuỗi, Gemini và Claude
    trả danh sách khối (chữ, suy luận, yêu cầu gọi công cụ). Chỉ lấy khối chữ.

    Khối có cờ `thought` bị loại: Gemini đánh dấu phần suy luận bằng cờ đó
    nhưng vẫn để type='text'. Không loại thì suy luận sẽ lẫn thẳng vào câu trả
    lời — người dùng đọc được cả những phỏng đoán mà mô hình đã tự bác bỏ.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        phan = []
        for khoi in content:
            if isinstance(khoi, str):
                phan.append(khoi)
            elif (
                isinstance(khoi, dict)
                and khoi.get("type") == "text"
                and not khoi.get("thought")
            ):
                phan.append(str(khoi.get("text", "")))
        return "".join(phan)
    return ""


def _reasoning_of(chunk: Any) -> str:
    """Lấy phần SUY LUẬN từ một mẩu tin nhắn, nếu nhà cung cấp có gửi.

    Ba nơi khác nhau tuỳ nhà cung cấp:
      - Groq / các API tương thích OpenAI: additional_kwargs['reasoning_content']
      - Anthropic: khối content type='thinking'
      - Google Gemini: khối content type='text' kèm cờ thought=True

    Không có thì trả về chuỗi rỗng — nơi gọi tự hiểu là mô hình này không lộ
    suy luận, và đơn giản không gửi event nào.
    """
    ak = getattr(chunk, "additional_kwargs", None) or {}
    tho = ak.get("reasoning_content") or ak.get("reasoning")
    if isinstance(tho, str) and tho:
        return tho

    content = getattr(chunk, "content", None)
    if isinstance(content, list):
        phan = []
        for khoi in content:
            if not isinstance(khoi, dict):
                continue
            if khoi.get("type") in ("thinking", "thinking_delta"):
                phan.append(str(khoi.get("thinking") or khoi.get("text") or ""))
            elif khoi.get("thought") and khoi.get("type") == "text":
                phan.append(str(khoi.get("text", "")))
        return "".join(phan)
    return ""


def _rut_gon(text: str, gioi_han: int = RESULT_DISPLAY_MAX) -> str:
    if len(text) <= gioi_han:
        return text
    con_lai = len(text) - gioi_han
    return f"{text[:gioi_han]}\n… (còn {con_lai} ký tự, xem đầy đủ trong trace)"


def _ket_qua_cong_cu(output: Any) -> tuple[str, bool]:
    """Bóc nội dung và trạng thái từ đầu ra của một công cụ.

    ToolNode bắt lỗi của công cụ và trả về một ToolMessage có status='error'
    thay vì ném ngoại lệ — nhờ vậy mô hình đọc được thông báo lỗi và tự xử lý.
    Nghĩa là lỗi công cụ KHÔNG làm luồng dừng, phải nhận ra qua chỗ này.
    """
    status = getattr(output, "status", None)
    if hasattr(output, "content"):
        return _text_of(output.content) or str(output.content), status == "error"
    return str(output), False


async def stream_graph_events(
    graph: Any,
    state: dict[str, Any],
    *,
    stream: EventStream,
    collector: StreamCollector,
    config: dict[str, Any] | None = None,
) -> AsyncIterator[dict[str, str]]:
    """Chạy đồ thị và sinh ra các khung SSE theo thời gian thực.

    Kết quả cuối cùng được ghi vào `collector`; hàm này chỉ sinh ra khung để
    gửi đi. Lỗi được biến thành `ErrorEvent` chứ không ném ra ngoài, vì luồng
    SSE đã mở rồi thì không đổi được mã HTTP nữa — báo lỗi bằng dữ liệu là
    cách duy nhất để client biết chuyện gì xảy ra.
    """
    dang_chay: dict[str, ToolCallRecord] = {}
    chu: list[str] = []
    nghi: list[str] = []

    try:
        async for event in graph.astream_events(state, config=config, version="v2"):
            loai = event["event"]

            # --- Mô hình đang nhả chữ ---
            if loai == "on_chat_model_stream":
                chunk = event["data"]["chunk"]

                # Suy luận trước, vì nó đến trước câu trả lời. Hai thứ này đi
                # theo hai đường riêng và KHÔNG được trộn vào nhau.
                suy_luan = _reasoning_of(chunk)
                if suy_luan:
                    nghi.append(suy_luan)
                    yield stream.emit(ThinkingEvent(content=suy_luan))

                text = _text_of(getattr(chunk, "content", ""))
                if text:
                    chu.append(text)
                    yield stream.emit(TokenEvent(content=text))

            # --- Mô hình nói xong một lượt: lấy số token ---
            elif loai == "on_chat_model_end":
                usage = getattr(event["data"].get("output"), "usage_metadata", None)
                if usage:
                    # Một lượt có thể gọi mô hình nhiều lần (mỗi vòng công cụ là
                    # một lần), nên phải cộng dồn chứ không gán đè.
                    collector.prompt_tokens = (collector.prompt_tokens or 0) + int(
                        usage.get("input_tokens", 0)
                    )
                    collector.completion_tokens = (
                        collector.completion_tokens or 0
                    ) + int(usage.get("output_tokens", 0))

            # --- Một công cụ bắt đầu chạy ---
            elif loai == "on_tool_start":
                call_id = str(event["run_id"])
                args = event["data"].get("input") or {}
                if not isinstance(args, dict):
                    args = {"input": str(args)}

                ban_ghi = ToolCallRecord(
                    call_id=call_id,
                    name=event["name"],
                    args=args,
                    started_at=datetime.now(UTC),
                )
                dang_chay[call_id] = ban_ghi
                collector.tool_calls.append(ban_ghi)

                yield stream.emit(
                    ToolCallStartEvent(id=call_id, name=ban_ghi.name, args=args)
                )

            # --- Công cụ chạy xong ---
            elif loai == "on_tool_end":
                call_id = str(event["run_id"])
                ban_ghi = dang_chay.pop(call_id, None)
                if ban_ghi is None:
                    # Không có cặp mở tương ứng — bỏ qua, gửi đi client cũng
                    # không biết ghép vào đâu.
                    logger.warning("Nhận on_tool_end không có on_tool_start: %s", call_id)
                    continue

                noi_dung, co_loi = _ket_qua_cong_cu(event["data"].get("output"))
                ban_ghi.duration_ms = int(
                    (time.perf_counter() - ban_ghi._bat_dau) * 1000
                )
                ban_ghi.status = "error" if co_loi else "ok"
                if co_loi:
                    ban_ghi.error = _rut_gon(noi_dung)
                else:
                    ban_ghi.result = _rut_gon(noi_dung)

                yield stream.emit(
                    ToolCallEndEvent(
                        id=call_id,
                        status=ban_ghi.status,
                        duration_ms=ban_ghi.duration_ms,
                        result=ban_ghi.result,
                        error=ban_ghi.error,
                    )
                )

    except asyncio.CancelledError:
        # Người dùng đóng tab hoặc bấm dừng. Không phải lỗi — để nơi gọi lo
        # việc lưu lại phần đã nói.
        collector.content = "".join(chu)
        collector.reasoning = "".join(nghi)
        raise

    except Exception as exc:
        logger.exception("Luồng trò chuyện gặp lỗi")
        collector.error = f"{type(exc).__name__}: {exc}"
        yield stream.emit(
            ErrorEvent(
                code=_ma_loi(exc),
                message=_thong_bao_loi(exc),
                retryable=_co_the_thu_lai(exc),
            )
        )

    finally:
        collector.content = "".join(chu)
        collector.reasoning = "".join(nghi)

        # Công cụ nào mở mà chưa đóng thì đánh dấu lỗi, đừng để nó nằm mãi ở
        # trạng thái "đang chạy" trong CSDL.
        for ban_ghi in dang_chay.values():
            ban_ghi.status = "error"
            ban_ghi.error = "Luồng kết thúc khi công cụ chưa trả kết quả"
            ban_ghi.duration_ms = int((time.perf_counter() - ban_ghi._bat_dau) * 1000)


# --------------------------------------------------------------------------
# Phân loại lỗi — để client biết nên hiện gì và có nên cho thử lại không
# --------------------------------------------------------------------------


def _ma_loi(exc: Exception) -> str:
    ten = type(exc).__name__.lower()
    chuoi = str(exc).lower()

    if "timeout" in ten or "timeout" in chuoi:
        return "llm_timeout"
    if "ratelimit" in ten or "rate limit" in chuoi or "429" in chuoi:
        return "llm_rate_limit"
    if "authentication" in ten or "api key" in chuoi or "401" in chuoi:
        return "llm_auth"
    if "recursion" in ten or "recursion" in chuoi:
        return "agent_loop"
    return "agent_error"


def _thong_bao_loi(exc: Exception) -> str:
    """Câu hiện cho người dùng. Chi tiết kỹ thuật nằm ở log máy chủ."""
    ma = _ma_loi(exc)
    return {
        "llm_timeout": "Mô hình trả lời quá lâu. Thử lại hoặc đổi sang model nhanh hơn.",
        "llm_rate_limit": "Đã chạm giới hạn gọi của nhà cung cấp. Chờ một lát rồi thử lại.",
        "llm_auth": "Khoá API không hợp lệ. Kiểm tra lại trong phần Cấu hình.",
        "agent_loop": "Trợ lý gọi công cụ quá nhiều lần mà chưa ra kết quả. Thử hỏi cụ thể hơn.",
    }.get(ma, f"Lỗi khi xử lý: {exc}")


def _co_the_thu_lai(exc: Exception) -> bool:
    return _ma_loi(exc) in {"llm_timeout", "llm_rate_limit"}


__all__ = [
    "RESULT_DISPLAY_MAX",
    "StreamCollector",
    "ToolCallRecord",
    "stream_graph_events",
]
