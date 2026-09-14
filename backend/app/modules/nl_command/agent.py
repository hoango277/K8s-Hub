"""Đồ thị xử lý một lượt trò chuyện.

Vòng chạy rất ngắn:

    người dùng hỏi -> [trợ lý] -> có gọi công cụ? -> [công cụ] -> [trợ lý] -> trả lời

`tools_condition` là thứ quyết định rẽ nhánh: nếu câu trả lời của mô hình có
kèm yêu cầu gọi công cụ thì đi tiếp sang nút công cụ, không thì kết thúc.
Vòng lặp này chạy đến khi mô hình không đòi gọi gì nữa.

Vì sao dùng LangGraph chứ không tự viết vòng while: LangGraph phát ra sự kiện
chi tiết cho từng bước (`astream_events`), và chính nhờ đó khung chat mới hiện
được "đang gọi công cụ X" theo thời gian thực. Tự viết thì phải tự làm lại
toàn bộ phần đó.

Chưa gắn checkpointer: lịch sử được nạp lại từ CSDL của chính hệ thống
(bảng `messages`) ở mỗi lượt, nên không cần LangGraph nhớ hộ. Khi làm bước
duyệt thao tác — cần dừng giữa chừng rồi chạy tiếp — thì mới cần checkpointer.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from app.integrations.llm.client import get_llm
from app.modules.nl_command.prompts import build_system_prompt
from app.modules.nl_command.state import ChatState
from app.modules.nl_command.tools import get_tools

logger = logging.getLogger(__name__)

# Chặn vòng lặp gọi công cụ chạy mãi. Mỗi vòng là 2 bước (trợ lý + công cụ),
# nên con số này cho phép khoảng 12 lần gọi công cụ trong một lượt.
RECURSION_LIMIT = 25


def build_chat_graph(
    *,
    provider: str | None = None,
    model: str | None = None,
    tools: Sequence[BaseTool] | None = None,
) -> Any:
    """Dựng đồ thị cho một lượt trò chuyện.

    Args:
        provider: Ép nhà cung cấp cho lượt này. Bỏ trống thì theo cấu hình.
        model:    Ép tên model cho lượt này.
        tools:    Ép danh sách công cụ. Chủ yếu dùng cho test.
    """
    cong_cu = list(get_tools() if tools is None else tools)
    llm = get_llm(provider=provider, model=model)

    # Không có công cụ nào thì đừng gọi bind_tools — vài nhà cung cấp sẽ báo
    # lỗi khi nhận danh sách rỗng.
    llm_da_gan = llm.bind_tools(cong_cu) if cong_cu else llm

    loi_nhac = SystemMessage(content=build_system_prompt(cong_cu))

    async def tro_ly(state: ChatState, config: RunnableConfig) -> dict[str, list[AnyMessage]]:
        """Hỏi mô hình.

        Lời nhắc hệ thống được ghép vào đây chứ không lưu trong trạng thái —
        nếu lưu, mỗi vòng lặp gọi công cụ sẽ thêm một bản nữa.

        Truyền `config` xuống `ainvoke` là BẮT BUỘC, đừng bỏ đi cho gọn.
        Từ Python 3.11 trở lên LangChain tự chuyền config qua contextvars nên
        bỏ quên vẫn chạy, nhưng trên 3.10 thì KHÔNG: mô hình chạy tách rời khỏi
        luồng sự kiện, và hậu quả là khung chat không nhận được chữ nào, chỉ
        thấy công cụ chạy. Lỗi đó không ném ngoại lệ, chỉ im lặng mất streaming
        — rất dễ tưởng nhầm là do nhà cung cấp. Đây cũng là lý do dự án đặt sàn
        Python ở 3.11 (xem pyproject.toml).
        """
        tra_loi = await llm_da_gan.ainvoke([loi_nhac, *state["messages"]], config)
        return {"messages": [tra_loi]}

    do_thi = StateGraph(ChatState)
    do_thi.add_node("tro_ly", tro_ly)
    do_thi.add_edge(START, "tro_ly")

    if cong_cu:
        do_thi.add_node("cong_cu", ToolNode(cong_cu))
        # tools_condition trả về "tools" khi mô hình đòi gọi công cụ, END khi không.
        do_thi.add_conditional_edges(
            "tro_ly",
            tools_condition,
            {"tools": "cong_cu", END: END},
        )
        do_thi.add_edge("cong_cu", "tro_ly")
    else:
        do_thi.add_edge("tro_ly", END)

    return do_thi.compile()


def history_to_messages(rows: Iterable[Any]) -> list[AnyMessage]:
    """Đổi lịch sử trong CSDL thành tin nhắn cho mô hình.

    CHỈ lấy phần chữ của người dùng và trợ lý. Các lần gọi công cụ ở lượt trước
    bị bỏ qua có chủ ý: muốn gửi lại chúng thì phải gửi kèm ĐỦ cặp yêu cầu gọi
    và kết quả trả về, thiếu một vế là nhà cung cấp trả lỗi. Kết quả tra cứu cũ
    cũng thường đã lỗi thời — bắt trợ lý tra lại thì đúng hơn là cho nó tin vào
    số liệu từ mười phút trước.
    """
    messages: list[AnyMessage] = []
    for row in rows:
        noi_dung = (row.content or "").strip()
        if not noi_dung:
            continue
        if row.role == "user":
            messages.append(HumanMessage(content=noi_dung))
        elif row.role == "assistant" and row.status == "complete":
            messages.append(AIMessage(content=noi_dung))
    return messages


__all__ = ["RECURSION_LIMIT", "build_chat_graph", "history_to_messages"]
