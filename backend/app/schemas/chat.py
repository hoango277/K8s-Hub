"""Kiểu dữ liệu vào/ra của các endpoint hội thoại.

Khác với `app/schemas/events.py` (những gì chảy qua SSE lúc trợ lý đang chạy),
file này mô tả những gì ĐỌC ĐƯỢC LẠI sau đó: danh sách hội thoại, lịch sử
tin nhắn, các lần gọi công cụ đã lưu.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MessageRole = Literal["user", "assistant", "system"]
MessageStatus = Literal["streaming", "complete", "error"]
ToolCallStatus = Literal["running", "ok", "error"]


class ThreadCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(
        default=None,
        max_length=120,
        description="Bỏ trống thì lấy câu hỏi đầu tiên làm tiêu đề",
    )
    cluster: str | None = Field(default=None, max_length=120)


class ThreadUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class ThreadOut(BaseModel):
    """Một dòng trong danh sách hội thoại ở thanh bên."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    cluster: str | None
    archived: bool
    created_at: datetime
    last_message_at: datetime | None


class ToolCallOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    call_id: str
    name: str
    args: dict[str, Any]
    result: str | None
    status: ToolCallStatus
    error: str | None
    duration_ms: int | None
    started_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    thread_id: uuid.UUID
    role: MessageRole
    content: str

    # Phần suy luận, nếu nhà cung cấp có lộ ra.
    reasoning: str | None = None

    position: int
    status: MessageStatus
    error: str | None
    created_at: datetime

    # Chỉ tin nhắn của trợ lý mới có.
    trace_id: str | None = None
    provider: str | None = None
    model: str | None = None
    latency_ms: int | None = None

    # Số token đã tốn. Bảng `messages` lưu sẵn từ đầu, nhưng trước đây không
    # khai ở đây nên API im lặng bỏ qua — nhìn từ ngoài cứ như hệ thống không
    # đếm được token. Đây là nguồn số liệu cho phần chi phí ở trang giám sát.
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    tool_calls: list[ToolCallOut] = Field(default_factory=list)


class ThreadDetail(ThreadOut):
    """Hội thoại kèm toàn bộ lịch sử — dùng khi mở lại một hội thoại cũ."""

    messages: list[MessageOut] = Field(default_factory=list)


class ChatRequest(BaseModel):
    """Nội dung người dùng gửi để bắt đầu một lượt trả lời."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=8000)

    # Ghi đè cho riêng lượt này, không đụng tới cấu hình chung.
    provider: str | None = Field(
        default=None, description="Ép nhà cung cấp cho lượt này. VD: 'google'"
    )
    model: str | None = Field(default=None, description="Ép tên model cho lượt này")


__all__ = [
    "ChatRequest",
    "MessageOut",
    "MessageRole",
    "MessageStatus",
    "ThreadCreate",
    "ThreadDetail",
    "ThreadOut",
    "ThreadUpdate",
    "ToolCallOut",
    "ToolCallStatus",
]
