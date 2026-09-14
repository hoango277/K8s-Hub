"""Công cụ trợ lý được phép gọi trong khung chat.

ĐÂY LÀ ĐIỂM GẮN DUY NHẤT. Muốn trợ lý làm được việc gì mới thì thêm công cụ
vào `get_tools()`, không sửa đồ thị và không sửa tầng streaming.

Ranh giới an toàn — đọc kỹ trước khi thêm:

  1. Công cụ trong file này CHỈ ĐƯỢC ĐỌC. Không có công cụ nào tạo/sửa/xoá tài
     nguyên trên cụm. Thao tác thay đổi đi theo đường riêng: trợ lý đề xuất một
     bản mô tả có cấu trúc, hệ thống chạy thử, người duyệt, rồi mới thực hiện.
  2. Không nhận chuỗi lệnh thô. Không có công cụ nào kiểu `run_kubectl(cmd)` —
     tham số phải là trường rời rạc để kiểm tra được trước khi chạy.
  3. Mô tả công cụ là thứ mô hình đọc để quyết định gọi hay không. Viết mô tả
     mơ hồ thì mô hình sẽ gọi sai lúc, và lỗi đó rất khó lần ra.

Chưa có công cụ tra cứu cụm vì tầng kết nối Kubernetes chưa làm xong
(app/integrations/k8s/client.py). Khi xong, thêm vào `get_tools()`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.core.config import get_settings
from app.integrations.llm.client import describe_config


@tool
def system_info(config: RunnableConfig) -> str:
    """Cho biết hệ thống K8s Hub đang được cấu hình thế nào.

    Dùng khi người dùng hỏi hệ thống đang chạy mô hình AI nào, đang ở chế độ
    thực thi nào, hay đang được phép thao tác trên namespace nào.
    """
    # `config` do LangChain tự tiêm vào, KHÔNG nằm trong schema mà mô hình nhìn
    # thấy — nên mô hình không thể (và không cần) truyền gì cho tham số này.
    #
    # Lấy nhà cung cấp và model từ đây chứ không từ cấu hình chung: người dùng
    # chọn được model cho RIÊNG một lượt chat. Đọc cấu hình chung thì trợ lý sẽ
    # khai sai về chính nó ngay sau khi người dùng đổi model trên giao diện.
    meta = (config or {}).get("metadata") or {}
    llm = describe_config(
        provider=meta.get("llm_provider"), model=meta.get("llm_model")
    )

    cau_hinh = get_settings()

    che_do = {
        "read_only": "chỉ đọc, không thực hiện thay đổi nào",
        "require_approval": "thay đổi phải được người duyệt trước khi chạy",
        "auto": "tự động thực hiện thay đổi, KHÔNG cần người duyệt",
    }.get(cau_hinh.K8S_EXECUTION_MODE, cau_hinh.K8S_EXECUTION_MODE)

    namespaces = cau_hinh.K8S_ALLOWED_NAMESPACES or ["(tất cả)"]

    return (
        f"Mô hình AI: {llm['provider']} / {llm['model']}\n"
        f"Gọi được công cụ: {'có' if llm['tool_calling'] else 'không'}\n"
        f"Chế độ thực thi: {cau_hinh.K8S_EXECUTION_MODE} — {che_do}\n"
        f"Namespace được phép: {', '.join(namespaces)}\n"
        f"Nguồn số liệu: Prometheus {cau_hinh.PROMETHEUS_URL}, Loki {cau_hinh.LOKI_URL}\n"
        f"Môi trường: {cau_hinh.APP_ENV}"
    )


@tool
def current_time() -> str:
    """Thời điểm hiện tại theo giờ UTC.

    Dùng khi cần tính khoảng cách thời gian, ví dụ pod khởi động lại cách đây
    bao lâu, hay khoảng thời gian nào cần lấy log.
    """
    bay_gio = datetime.now(UTC)
    return f"{bay_gio.isoformat(timespec='seconds')} (UTC)"


# Thứ tự trong danh sách cũng là thứ tự mô hình nhìn thấy.
CHAT_TOOLS: list[BaseTool] = [system_info, current_time]


def get_tools() -> list[BaseTool]:
    """Danh sách công cụ cho một lượt trò chuyện.

    Trả về bản sao để nơi gọi có thêm/bớt cũng không ảnh hưởng danh sách gốc.
    """
    return list(CHAT_TOOLS)


__all__ = ["CHAT_TOOLS", "get_tools"]
