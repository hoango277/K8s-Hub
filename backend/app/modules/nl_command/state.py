"""Trạng thái mà đồ thị LangGraph mang theo giữa các bước.

Chỉ có một thứ duy nhất: danh sách tin nhắn. `add_messages` là bộ gộp của
LangGraph — nút nào trả về tin nhắn mới thì chúng được NỐI vào danh sách cũ
chứ không ghi đè, và tin nhắn trùng id thì được thay thế. Không có nó, mỗi
vòng lặp gọi công cụ sẽ xoá sạch ngữ cảnh phía trước.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class ChatState(TypedDict):
    """Trạng thái của một lượt trò chuyện."""

    messages: Annotated[list[AnyMessage], add_messages]


__all__ = ["ChatState"]
