"""Sự kiện streaming đẩy từ backend về client qua SSE.

===========================================================================
 HỢP ĐỒNG GIỮA BACKEND VÀ FRONTEND
 File này phải khớp 1-1 với `frontend/src/types/events.ts`.
 Sửa ở đây thì BẮT BUỘC sửa bên kia và báo cả nhóm.
===========================================================================

Dùng chung cho hai luồng:
  - Hội thoại ra lệnh  (app/modules/nl_command)
  - Tiến trình chẩn đoán (app/modules/rca)

Cách đóng gói lên đường truyền: xem `to_sse()` ở cuối file.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# --------------------------------------------------------------------------
# Kiểu dùng lại
# --------------------------------------------------------------------------

ToolStatus: TypeAlias = Literal["ok", "error"]
StepStatus: TypeAlias = Literal["running", "done", "error"]
DangerLevel: TypeAlias = Literal["safe", "caution", "dangerous"]


class BaseEvent(BaseModel):
    """Phần chung của mọi event."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(
        default=0,
        description=(
            "Số thứ tự tăng dần trong một luồng, bắt đầu từ 1. "
            "Client dùng để phát hiện mất event và để resume sau khi mất kết nối "
            "(gửi lại qua header Last-Event-ID). Do EventStream tự gán."
        ),
    )


# --------------------------------------------------------------------------
# Các loại event
# --------------------------------------------------------------------------


class TokenEvent(BaseEvent):
    """Một mẩu văn bản của câu trả lời. Client nối các mẩu lại theo thứ tự."""

    type: Literal["token"] = "token"
    content: str


class ThinkingEvent(BaseEvent):
    """Một mẩu SUY LUẬN của mô hình, không phải câu trả lời.

    Đây là phần mô hình tự nghĩ trước khi nói — nó cân nhắc gì, định tra cứu
    gì. Rất đáng hiện ra trong vận hành: người trực nhìn được trợ lý đang đi
    theo hướng nào, và bắt được sớm khi nó hiểu sai đề bài.

    Hiển thị TÁCH BIỆT với câu trả lời và phải nhìn ra ngay là suy luận. Trộn
    lẫn hai thứ là nguy hiểm: suy luận thường chứa phỏng đoán và cả những kết
    luận sai mà mô hình tự bác bỏ ngay sau đó.

    Không phải nhà cung cấp nào cũng có. Không có thì đơn giản là không gửi
    event nào loại này.
    """

    type: Literal["thinking"] = "thinking"
    content: str


class StepEvent(BaseEvent):
    """Báo tiến trình một bước xử lý.

    Chủ yếu dùng cho chẩn đoán ("Đang thu thập nhật ký..."), nhưng luồng ra lệnh
    cũng dùng được. Nếu `key` trùng với một step đã gửi trước đó thì client CẬP NHẬT
    dòng cũ chứ không thêm dòng mới — nhờ vậy mới đổi được trạng thái running → done.
    """

    type: Literal["step"] = "step"
    key: str = Field(description="Mã bước, ổn định trong một luồng. VD: 'collect_logs'")
    label: str = Field(description="Chữ hiển thị cho người dùng")
    status: StepStatus = "running"


class ToolCallStartEvent(BaseEvent):
    """Trợ lý bắt đầu gọi một công cụ."""

    type: Literal["tool_call_start"] = "tool_call_start"
    id: str = Field(description="Mã lần gọi, dùng để ghép với tool_call_end")
    name: str = Field(description="Tên công cụ, VD: 'list_resources'")
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallEndEvent(BaseEvent):
    """Công cụ chạy xong. `id` phải trùng với tool_call_start tương ứng."""

    type: Literal["tool_call_end"] = "tool_call_end"
    id: str
    status: ToolStatus
    duration_ms: int
    result: str | None = Field(
        default=None,
        description="Kết quả ĐÃ RÚT GỌN để hiển thị. Bản đầy đủ xem trong Langfuse.",
    )
    error: str | None = Field(default=None, description="Chỉ có khi status='error'")


class PlanStep(BaseModel):
    """Một bước trong kế hoạch trợ lý đề xuất."""

    model_config = ConfigDict(extra="forbid")

    order: int
    description: str


class PlanEvent(BaseEvent):
    """Kế hoạch trợ lý dự định làm, gửi TRƯỚC khi xin duyệt."""

    type: Literal["plan"] = "plan"
    steps: list[PlanStep]
    summary: str | None = None


class ApprovalRequiredEvent(BaseEvent):
    """Luồng dừng lại chờ người duyệt.

    Sau event này luồng SSE KHÔNG kết thúc mà treo chờ. Client gọi
    POST /approvals/{approval_id}/approve|reject qua một request riêng.
    """

    type: Literal["approval_required"] = "approval_required"
    approval_id: str
    summary: str = Field(description="VD: 'Tăng số bản chạy của api từ 1 lên 3'")
    diff: str = Field(description="So sánh trước/sau, dạng unified diff YAML")
    danger_level: DangerLevel = "caution"
    dry_run_output: str | None = Field(
        default=None, description="Kết quả chạy thử không ăn thật"
    )


class ApprovalResolvedEvent(BaseEvent):
    """Người dùng đã quyết định. Gửi ngay trước khi luồng chạy tiếp."""

    type: Literal["approval_resolved"] = "approval_resolved"
    approval_id: str
    approved: bool
    decided_by: str | None = None
    reason: str | None = Field(default=None, description="Lý do khi từ chối")


class VerifyResultEvent(BaseEvent):
    """Kết quả kiểm tra lại sau khi đã thực hiện thao tác lên cụm."""

    type: Literal["verify_result"] = "verify_result"
    ok: bool
    message: str = Field(description="VD: 'Đã lên đủ 3/3 bản chạy sau 12 giây'")


class ErrorEvent(BaseEvent):
    """Có lỗi. Nếu retryable=False thì sau event này luồng sẽ kết thúc."""

    type: Literal["error"] = "error"
    code: str = Field(description="VD: 'llm_timeout', 'guardrail_blocked', 'k8s_forbidden'")
    message: str
    retryable: bool = False


class DoneEvent(BaseEvent):
    """Luồng kết thúc bình thường. Luôn là event cuối cùng."""

    type: Literal["done"] = "done"
    message_id: str | None = Field(default=None, description="Id bản ghi trong CSDL")
    trace_id: str | None = Field(
        default=None, description="Id trace Langfuse, để client mở link xem chi tiết"
    )


class HeartbeatEvent(BaseEvent):
    """Nhịp giữ kết nối, gửi mỗi ~15 giây khi không có gì để gửi.

    Không có nó thì proxy (nginx, ingress) sẽ cắt kết nối đang rảnh.
    Client bỏ qua event này.
    """

    type: Literal["heartbeat"] = "heartbeat"


# --------------------------------------------------------------------------
# Union + tiện ích
# --------------------------------------------------------------------------

AgentEvent = Annotated[
    TokenEvent
    | ThinkingEvent
    | StepEvent
    | ToolCallStartEvent
    | ToolCallEndEvent
    | PlanEvent
    | ApprovalRequiredEvent
    | ApprovalResolvedEvent
    | VerifyResultEvent
    | ErrorEvent
    | DoneEvent
    | HeartbeatEvent,
    Field(discriminator="type"),
]

AgentEventAdapter: TypeAdapter[AgentEvent] = TypeAdapter(AgentEvent)


def to_sse(event: BaseEvent) -> dict[str, str]:
    """Đóng gói event thành khung SSE cho `sse_starlette.EventSourceResponse`.

    Đặt tên event theo `type` để client vừa nghe được từng loại riêng
    (addEventListener('token', ...)) vừa nghe được tất cả.
    """
    return {
        "event": event.type,  # type: ignore[attr-defined]
        "id": str(event.seq),
        "data": event.model_dump_json(exclude_none=True),
    }


class EventStream:
    """Đánh số thứ tự và đóng gói event.

    Mỗi lần trả lời tạo một instance mới:

        stream = EventStream()
        yield stream.emit(TokenEvent(content="Xin"))
        yield stream.emit(TokenEvent(content=" chào"))
        yield stream.emit(DoneEvent(trace_id=trace_id))
    """

    def __init__(self, start: int = 0) -> None:
        self._seq = start

    def emit(self, event: BaseEvent) -> dict[str, str]:
        self._seq += 1
        event.seq = self._seq
        return to_sse(event)


__all__ = [
    "AgentEvent",
    "AgentEventAdapter",
    "ApprovalRequiredEvent",
    "ApprovalResolvedEvent",
    "BaseEvent",
    "DangerLevel",
    "DoneEvent",
    "ErrorEvent",
    "EventStream",
    "HeartbeatEvent",
    "PlanEvent",
    "PlanStep",
    "StepEvent",
    "StepStatus",
    "ThinkingEvent",
    "TokenEvent",
    "ToolCallEndEvent",
    "ToolCallStartEvent",
    "ToolStatus",
    "VerifyResultEvent",
    "to_sse",
]
