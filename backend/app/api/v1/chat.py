"""Các endpoint của khung trò chuyện.

    POST   /chat/threads                  tạo hội thoại
    GET    /chat/threads                  danh sách hội thoại
    GET    /chat/threads/{id}             hội thoại kèm toàn bộ lịch sử
    PATCH  /chat/threads/{id}             đổi tiêu đề / lưu trữ
    DELETE /chat/threads/{id}             xoá hẳn
    GET    /chat/threads/{id}/messages    chỉ lịch sử tin nhắn
    POST   /chat/threads/{id}/stream      gửi câu hỏi, nhận trả lời theo luồng
    GET    /chat/providers                nhà cung cấp LLM + đã có khoá chưa
    GET    /chat/models                   model dùng được, hỏi thẳng nhà cung cấp
    GET    /chat/tools                    công cụ trợ lý đang có

VỀ ENDPOINT STREAM — ba điểm dễ sai:

  1. Việc chuẩn bị (kiểm tra quyền, ghi câu hỏi) làm XONG và COMMIT trước khi
     mở luồng. Luồng đã mở rồi thì không đổi được mã HTTP nữa: hội thoại không
     tồn tại mà phát hiện muộn thì client nhận 200 kèm một sự kiện lỗi, thay vì
     404 rõ ràng.

  2. Phần chạy trong luồng dùng PHIÊN CSDL RIÊNG, không dùng phiên của request.
     Phiên của request giữ một kết nối trong bộ gộp cho tới khi response kết
     thúc — mà response ở đây có thể kéo dài hàng phút. Với Supabase (bộ gộp
     chỉ cho vài kết nối) thì giữ như vậy là làm nghẽn cả hệ thống.

  3. Người dùng đóng tab giữa chừng thì phần trợ lý đã nói vẫn được lưu. Mở lại
     hội thoại phải thấy đúng những gì đã xảy ra, kể cả khi nó dở dang.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sse_starlette.sse import EventSourceResponse

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.db.models.thread import ChatThread
from app.db.session import get_sessionmaker
from app.integrations.llm.catalog import ModelCatalog
from app.integrations.llm.catalog import list_models as catalog_models
from app.integrations.llm.streaming import StreamCollector, stream_graph_events
from app.modules.nl_command.agent import (
    RECURSION_LIMIT,
    build_chat_graph,
    history_to_messages,
)
from app.modules.nl_command.tools import CHAT_TOOLS
from app.schemas.chat import (
    ChatRequest,
    MessageOut,
    ThreadCreate,
    ThreadDetail,
    ThreadOut,
    ThreadUpdate,
)
from app.schemas.events import DoneEvent, ErrorEvent, EventStream
from app.services import thread_service as svc

logger = logging.getLogger(__name__)

router = APIRouter()

# Nhịp giữ kết nối. Không có nó, proxy đứng giữa sẽ cắt kết nối đang rảnh —
# mà "rảnh" là chuyện bình thường khi trợ lý đang chờ một công cụ chạy xong.
# sse-starlette gửi dạng dòng chú thích, client tự bỏ qua, không lẫn vào dữ liệu.
PING_SECONDS = 15

# Các tác vụ ghi kết quả đang chạy ở nền.
#
# asyncio chỉ giữ tham chiếu YẾU tới task, nên không cất vào đây thì trình dọn
# rác có thể thu một task đang ghi dở và bản ghi kẹt lại vĩnh viễn ở trạng thái
# "streaming".
_dang_ghi: set[asyncio.Task[None]] = set()


# --------------------------------------------------------------------------
# Hội thoại
# --------------------------------------------------------------------------


async def _thread_or_404(db: Any, user: Any, thread_id: uuid.UUID) -> ChatThread:
    thread = await svc.get_thread(db, user, thread_id)
    if thread is None:
        # Cố tình không phân biệt "không có" với "của người khác" — trả lời
        # khác nhau là đã lộ ra hội thoại đó có tồn tại.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy hội thoại"
        )
    return thread


@router.post("/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(payload: ThreadCreate, db: DbSession, user: CurrentUser) -> Any:
    thread = await svc.create_thread(
        db, user, title=payload.title, cluster=payload.cluster
    )
    # Chốt NGAY, đừng đợi `get_session` chốt hộ lúc dọn dẹp.
    #
    # Từ FastAPI 0.106, phần sau `yield` của dependency chạy SAU khi response đã
    # gửi đi. Nghĩa là client nhận 201 rồi mà giao dịch vẫn chưa chốt — giao diện
    # lập tức gọi tiếp lên hội thoại vừa tạo thì gặp 404. Đã tái hiện được.
    await db.commit()
    return thread


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(
    db: DbSession,
    user: CurrentUser,
    include_archived: bool = Query(False, description="Kèm cả hội thoại đã lưu trữ"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Any:
    return await svc.list_threads(
        db, user, include_archived=include_archived, limit=limit, offset=offset
    )


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: uuid.UUID, db: DbSession, user: CurrentUser) -> Any:
    thread = await _thread_or_404(db, user, thread_id)
    messages = await svc.list_messages(db, thread.id)
    return ThreadDetail(
        **ThreadOut.model_validate(thread).model_dump(),
        messages=[MessageOut.model_validate(m) for m in messages],
    )


@router.patch("/threads/{thread_id}", response_model=ThreadOut)
async def update_thread(
    thread_id: uuid.UUID, payload: ThreadUpdate, db: DbSession, user: CurrentUser
) -> Any:
    thread = await _thread_or_404(db, user, thread_id)
    thread = await svc.update_thread(
        db, thread, title=payload.title, archived=payload.archived
    )
    await db.commit()  # xem chú thích ở create_thread
    return thread


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Response:
    thread = await _thread_or_404(db, user, thread_id)
    await svc.delete_thread(db, thread)
    await db.commit()  # xem chú thích ở create_thread
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_messages(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Any:
    thread = await _thread_or_404(db, user, thread_id)
    return await svc.list_messages(db, thread.id)


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    """Nhà cung cấp đang khai báo, kèm việc đã điền khoá API hay chưa.

    Giao diện dùng để hiện ô chọn và cảnh báo sớm: chọn nhà cung cấp chưa có
    khoá thì báo ngay, thay vì để người dùng gõ xong câu hỏi rồi mới nhận lỗi.
    """
    config = get_settings()

    ra = []
    for ten in sorted(config.LLM_PROVIDERS):
        spec = config.llm_provider(ten)
        ra.append(
            {
                "name": ten,
                "api_key_set": bool(
                    str(getattr(config, spec.api_key_field, "") or "").strip()
                ),
                "api_key_field": spec.api_key_field,
                "supports_tool_calling": spec.supports_tool_calling,
                # Model riêng của nhà cung cấp này, KHÔNG dùng llm_model_name():
                # hàm đó ưu tiên LLM_MODEL trong .env, nên sẽ trả về cùng một
                # tên cho cả ba nhà cung cấp. Đổi sang Google mà giao diện lại
                # chọn sẵn một model của Groq thì gửi đi là lỗi ngay.
                "default_model": spec.model,
                "fast_model": spec.fast_model,
                "notes": spec.notes,
            }
        )

    return {
        "providers": ra,
        # Lựa chọn mặc định khi người dùng chưa chọn gì.
        "current": {
            "provider": config.LLM_PROVIDER,
            "model": config.llm_model_name(),
        },
    }


@router.get("/models", response_model=ModelCatalog)
async def list_models(
    provider: str | None = Query(None, description="Bỏ trống thì lấy nhà cung cấp đang đặt"),
    refresh: bool = Query(False, description="Bỏ qua bộ nhớ đệm, hỏi lại nhà cung cấp"),
) -> Any:
    """Danh sách model dùng được, hỏi thẳng nhà cung cấp.

    Không bao giờ trả lỗi: gọi API hỏng thì rơi về model khai trong cấu hình và
    ghi lý do vào trường `error` để giao diện hiện cho người dùng biết.
    """
    config = get_settings()
    ten = provider or config.LLM_PROVIDER
    try:
        config.llm_provider(ten)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return await catalog_models(ten, refresh=refresh)


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """Công cụ trợ lý đang có, để giao diện hiển thị cho người dùng biết."""
    return {
        "tools": [
            {
                "name": t.name,
                "description": (t.description or "").strip().split("\n")[0],
            }
            for t in CHAT_TOOLS
        ]
    }


# --------------------------------------------------------------------------
# Trả lời theo luồng
# --------------------------------------------------------------------------


@router.post("/threads/{thread_id}/stream")
async def stream_reply(
    thread_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> EventSourceResponse:
    """Gửi một câu hỏi và nhận câu trả lời theo luồng (SSE).

    Client đọc bằng `fetch` + ReadableStream chứ không dùng `EventSource`, vì
    `EventSource` chỉ gửi được GET nên không mang theo nội dung câu hỏi.
    """
    config = get_settings()
    thread = await _thread_or_404(db, user, thread_id)

    # Kiểm tra nhà cung cấp trước khi ghi gì — sai tên thì trả 400 luôn.
    ten_provider = payload.provider or config.LLM_PROVIDER
    try:
        config.llm_provider(ten_provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    ten_model = payload.model or config.llm_model_name(provider=ten_provider)
    trace_id = uuid.uuid4().hex

    await svc.add_user_message(db, thread, payload.content)
    assistant = await svc.start_assistant_message(
        db, thread, provider=ten_provider, model=ten_model, trace_id=trace_id
    )
    lich_su = await svc.list_messages(db, thread.id, limit=svc.HISTORY_LIMIT)

    # Chốt trước khi mở luồng: trả kết nối về bộ gộp, và câu hỏi không bị mất
    # nếu người dùng đóng tab ngay sau khi bấm gửi.
    await db.commit()

    assistant_id = assistant.id
    messages = history_to_messages(lich_su)

    async def phat_su_kien() -> AsyncIterator[dict[str, str]]:
        stream = EventStream()
        collector = StreamCollector()
        bat_dau = time.perf_counter()
        bi_huy = False

        try:
            graph = build_chat_graph(provider=payload.provider, model=payload.model)
        except Exception as exc:
            # Thiếu khoá API, chưa cài gói của nhà cung cấp… Luồng đã mở nên
            # chỉ còn cách báo bằng sự kiện.
            logger.exception("Không dựng được trợ lý")
            yield stream.emit(
                ErrorEvent(code="llm_config", message=str(exc), retryable=False)
            )
            await _ghi_ket_qua(
                assistant_id, collector, latency_ms=0, error=str(exc)
            )
            yield stream.emit(DoneEvent(message_id=str(assistant_id), trace_id=trace_id))
            return

        try:
            async for frame in stream_graph_events(
                graph,
                {"messages": messages},
                stream=stream,
                collector=collector,
                config={
                    "recursion_limit": RECURSION_LIMIT,
                    "run_id": uuid.UUID(trace_id),
                    "metadata": {
                        "thread_id": str(thread_id),
                        "message_id": str(assistant_id),
                        "user": user.email,
                        # Công cụ đọc hai giá trị này để tự khai đúng nhà cung
                        # cấp và model ĐANG chạy, thay vì cấu hình chung.
                        "llm_provider": ten_provider,
                        "llm_model": ten_model,
                    },
                },
            ):
                # Client đã bỏ đi thì dừng sớm, đừng tốn thêm tiền gọi model.
                if await request.is_disconnected():
                    bi_huy = True
                    break
                yield frame

        except asyncio.CancelledError:
            bi_huy = True
            raise

        finally:
            # Chạy cả khi bị huỷ: phần trợ lý đã nói vẫn phải được lưu.
            #
            # Việc ghi phải nằm trong một task RIÊNG và được `shield` che lại.
            # Lý do: khi người dùng đóng tab, sse-starlette huỷ chính task đang
            # chạy hàm này. Cứ `await` thẳng thì lệnh ghi bị huỷ ngay ở điểm
            # chờ đầu tiên — kết nối CSDL bị cắt giữa chừng và bản ghi nằm mãi
            # ở trạng thái "streaming", trái đúng điều ghi ở đầu file này.
            # Task riêng không nằm trong phạm vi huỷ của sse-starlette nên nó
            # chạy tiếp tới khi ghi xong.
            ghi = asyncio.create_task(
                _ghi_ket_qua(
                    assistant_id,
                    collector,
                    latency_ms=int((time.perf_counter() - bat_dau) * 1000),
                    error=collector.error
                    or ("Người dùng dừng giữa chừng" if bi_huy else None),
                )
            )
            _dang_ghi.add(ghi)
            ghi.add_done_callback(_dang_ghi.discard)

            # Luồng chạy trọn vẹn thì vẫn chờ ghi xong TRƯỚC khi phát `done`:
            # client nạp lại hội thoại ngay khi nhận `done`, chờ ở đây mới bảo
            # đảm nó đọc được bản đã chốt chứ không phải bản dở dang.
            # Bị huỷ thì `shield` để việc ghi chạy nốt ở nền, còn lệnh huỷ vẫn
            # lan ra bình thường.
            await asyncio.shield(ghi)

        yield stream.emit(DoneEvent(message_id=str(assistant_id), trace_id=trace_id))

    return EventSourceResponse(phat_su_kien(), ping=PING_SECONDS)


async def _ghi_ket_qua(
    message_id: uuid.UUID,
    collector: StreamCollector,
    *,
    latency_ms: int,
    error: str | None,
) -> None:
    """Lưu kết quả bằng một phiên CSDL riêng.

    Không dùng phiên của request: tới lúc này nó có thể đã bị đóng, và giữ nó
    mở suốt luồng thì chiếm mất kết nối trong bộ gộp.

    Lỗi khi ghi được nuốt lại và chỉ ghi log — luồng SSE đã gần xong, ném lỗi
    ở đây chỉ làm người dùng mất luôn câu trả lời vừa đọc trên màn hình.
    """
    from app.db.models.message import Message  # tránh vòng import lúc khởi động

    try:
        async with get_sessionmaker()() as db:
            message = await db.get(Message, message_id)
            if message is None:
                logger.warning("Không thấy tin nhắn %s để ghi kết quả", message_id)
                return
            await svc.finish_assistant_message(
                db,
                message,
                content=collector.content,
                reasoning=collector.reasoning,
                tool_calls=collector.tool_calls_as_dicts(),
                latency_ms=latency_ms,
                prompt_tokens=collector.prompt_tokens,
                completion_tokens=collector.completion_tokens,
                error=error,
            )
            await db.commit()
    except Exception:
        logger.exception("Không ghi được kết quả cho tin nhắn %s", message_id)
