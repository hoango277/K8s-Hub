"""Chat endpoints.

    POST   /chat/threads                  create a conversation
    GET    /chat/threads                  list conversations
    GET    /chat/threads/{id}             a conversation with its full history
    PATCH  /chat/threads/{id}             rename / archive
    DELETE /chat/threads/{id}             delete permanently
    GET    /chat/threads/{id}/messages    message history only
    POST   /chat/threads/{id}/stream      send a question, receive a streamed answer
    GET    /chat/providers                LLM providers + whether their key is set
    GET    /chat/models                   usable models, asked straight from the provider
    GET    /chat/tools                    the assistant's current tools

ABOUT THE STREAM ENDPOINT — three easy mistakes:

  1. All preparation (permission check, storing the question) is DONE and
     COMMITTED before the stream opens. Once the stream is open the HTTP status
     can no longer change: discovering late that the conversation does not
     exist would give the client a 200 with an error event instead of a clean
     404.

  2. The streaming part uses its OWN database session, not the request's. The
     request session holds a pooled connection until the response ends — and
     this response can last minutes. With Supabase (a pooler with only a few
     connections) that would choke the whole system.

  3. If the user closes the tab mid-answer, what the assistant already said is
     still saved. Reopening the conversation must show exactly what happened,
     even if it was cut short.
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
from app.core.telemetry import CHAT_STREAMS_ACTIVE, record_chat_turn
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
from app.modules.observability.langfuse_client import get_callback_handler
from app.modules.observability.tracing import new_trace_id
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

# Keep-alive interval. Without it, an intermediate proxy cuts idle connections —
# and being "idle" is normal while the assistant waits for a tool to finish.
# sse-starlette sends it as a comment line that clients ignore.
PING_SECONDS = 15

# Result-saving tasks running in the background.
#
# asyncio only keeps WEAK references to tasks, so without this set the garbage
# collector could reclaim a task halfway through saving and the record would be
# stuck in the "streaming" state forever.
_pending_saves: set[asyncio.Task[None]] = set()


# --------------------------------------------------------------------------
# Conversations
# --------------------------------------------------------------------------


async def _thread_or_404(db: Any, user: Any, thread_id: uuid.UUID) -> ChatThread:
    thread = await svc.get_thread(db, user, thread_id)
    if thread is None:
        # Deliberately no distinction between "does not exist" and "belongs to
        # someone else" — answering differently would reveal that it exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        )
    return thread


@router.post("/threads", response_model=ThreadOut, status_code=status.HTTP_201_CREATED)
async def create_thread(payload: ThreadCreate, db: DbSession, user: CurrentUser) -> Any:
    thread = await svc.create_thread(
        db, user, title=payload.title, cluster=payload.cluster
    )
    # Commit NOW; do not wait for `get_session` to commit during teardown.
    #
    # Since FastAPI 0.106 the code after a dependency's `yield` runs AFTER the
    # response has been sent. So the client gets its 201 while the transaction
    # is still uncommitted — and the UI immediately calling the new
    # conversation gets a 404. Reproduced.
    await db.commit()
    return thread


@router.get("/threads", response_model=list[ThreadOut])
async def list_threads(
    db: DbSession,
    user: CurrentUser,
    include_archived: bool = Query(False, description="Include archived conversations"),
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
    await db.commit()  # see the note in create_thread
    return thread


@router.delete("/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thread(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Response:
    thread = await _thread_or_404(db, user, thread_id)
    await svc.delete_thread(db, thread)
    await db.commit()  # see the note in create_thread
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
async def list_messages(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> Any:
    thread = await _thread_or_404(db, user, thread_id)
    return await svc.list_messages(db, thread.id)


@router.get("/providers")
async def list_providers() -> dict[str, Any]:
    """Declared providers, and whether their API key is set.

    The UI uses this to fill the picker and warn early: choosing a provider
    without a key is flagged right away instead of after the user has typed a
    question.
    """
    config = get_settings()

    providers = []
    for name in sorted(config.LLM_PROVIDERS):
        spec = config.llm_provider(name)
        providers.append(
            {
                "name": name,
                "api_key_set": bool(
                    str(getattr(config, spec.api_key_field, "") or "").strip()
                ),
                "api_key_field": spec.api_key_field,
                "supports_tool_calling": spec.supports_tool_calling,
                # THIS provider's own default model — switching to Google with a
                # Groq model still selected would fail on send.
                "default_model": spec.model,
                "fast_model": spec.fast_model,
                "notes": spec.notes,
            }
        )

    return {
        "providers": providers,
        # Default selection when the user has not picked anything.
        "current": {
            "provider": config.llm_default_provider(),
            "model": config.llm_model_name(),
        },
    }


@router.get("/models", response_model=ModelCatalog)
async def list_models(
    provider: str | None = Query(None, description="Leave empty for the default provider"),
    refresh: bool = Query(False, description="Bypass the cache and ask the provider again"),
) -> Any:
    """Usable models, asked straight from the provider.

    Never fails: when the API call breaks it falls back to the models declared
    in the provider spec and puts the reason in `error` for the UI to show.
    """
    config = get_settings()
    name = provider or config.llm_default_provider()
    try:
        config.llm_provider(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    return await catalog_models(name, refresh=refresh)


@router.get("/tools")
async def list_tools() -> dict[str, Any]:
    """The assistant's current tools, for the UI to show."""
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
# Streamed answers
# --------------------------------------------------------------------------


@router.post("/threads/{thread_id}/stream")
async def stream_reply(
    thread_id: uuid.UUID,
    payload: ChatRequest,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> EventSourceResponse:
    """Send a question and receive the answer as a stream (SSE).

    The client reads it with `fetch` + ReadableStream, not `EventSource`,
    because `EventSource` can only send GET and cannot carry the question body.
    """
    config = get_settings()
    thread = await _thread_or_404(db, user, thread_id)

    # Validate the provider before writing anything — a bad name returns 400.
    provider_name = payload.provider or config.llm_default_provider()
    try:
        config.llm_provider(provider_name)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    model_name = payload.model or config.llm_model_name(provider=provider_name)

    # Generate the trace id FIRST, then force Langfuse to use it (see
    # tracing.py). That way the id in the `messages` table always equals the id
    # in Langfuse — required for `impact.py` to join traces with the audit log.
    trace_id = new_trace_id()

    await svc.add_user_message(db, thread, payload.content)
    assistant = await svc.start_assistant_message(
        db, thread, provider=provider_name, model=model_name, trace_id=trace_id
    )
    history = await svc.list_messages(db, thread.id, limit=svc.HISTORY_LIMIT)

    # Commit before opening the stream: returns the connection to the pool, and
    # the question is not lost if the user closes the tab right after sending.
    await db.commit()

    assistant_id = assistant.id
    messages = history_to_messages(history)

    async def emit_events() -> AsyncIterator[dict[str, str]]:
        stream = EventStream()
        collector = StreamCollector()
        started = time.perf_counter()
        cancelled = False
        # Decremented on EVERY exit path below; a gauge that only climbs
        # would falsely report leaking streams.
        CHAT_STREAMS_ACTIVE.inc()

        # With Langfuse disabled this list is empty and the graph runs as usual.
        handler = get_callback_handler(trace_id=trace_id)
        callbacks = [handler] if handler is not None else []

        try:
            graph = build_chat_graph(provider=payload.provider, model=payload.model)
        except Exception as exc:
            # Missing API key, provider package not installed… The stream is
            # already open, so the only way to report it is an event.
            logger.exception("Could not build the assistant")
            yield stream.emit(
                ErrorEvent(code="llm_config", message=str(exc), retryable=False)
            )
            await _save_result(
                assistant_id, collector, latency_ms=0, error=str(exc)
            )
            CHAT_STREAMS_ACTIVE.dec()
            record_chat_turn(
                provider=provider_name, model=model_name, outcome="error",
                seconds=time.perf_counter() - started,
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
                    "callbacks": callbacks,
                    "metadata": {
                        "thread_id": str(thread_id),
                        "message_id": str(assistant_id),
                        "user": user.email,
                        # Tools read these two values to report the provider and
                        # model ACTUALLY running, not the global configuration.
                        "llm_provider": provider_name,
                        "llm_model": model_name,
                        # Read by the Langfuse CallbackHandler: without them the
                        # trace's userId/sessionId stay empty, and Langfuse can't
                        # group usage and cost per person or per conversation.
                        "langfuse_user_id": user.email,
                        "langfuse_session_id": str(thread_id),
                        "langfuse_tags": [provider_name],
                    },
                },
            ):
                # The client left: stop early, do not keep paying for the model.
                if await request.is_disconnected():
                    cancelled = True
                    break
                yield frame

        except asyncio.CancelledError:
            cancelled = True
            raise

        finally:
            CHAT_STREAMS_ACTIVE.dec()
            record_chat_turn(
                provider=provider_name,
                model=model_name,
                outcome="cancelled" if cancelled else ("error" if collector.error else "ok"),
                seconds=time.perf_counter() - started,
            )

            # Runs even when cancelled: what the assistant said must be saved.
            #
            # The save MUST run in its OWN task, protected by `shield`. When the
            # user closes the tab, sse-starlette cancels the very task running
            # this function. Awaiting the save directly would cancel it at its
            # first await — the DB connection is cut mid-write and the record
            # stays "streaming" forever, contradicting point 3 above. A separate
            # task is outside sse-starlette's cancel scope, so it finishes.
            save = asyncio.create_task(
                _save_result(
                    assistant_id,
                    collector,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                    error=collector.error
                    or ("Stopped by the user" if cancelled else None),
                )
            )
            _pending_saves.add(save)
            save.add_done_callback(_pending_saves.discard)

            # On a complete run, still wait for the save BEFORE emitting `done`:
            # the client reloads the conversation as soon as it sees `done`, and
            # waiting here guarantees it reads the final record, not a partial
            # one. When cancelled, `shield` lets the save finish in the
            # background while the cancellation propagates normally.
            await asyncio.shield(save)

        yield stream.emit(DoneEvent(message_id=str(assistant_id), trace_id=trace_id))

    return EventSourceResponse(emit_events(), ping=PING_SECONDS)


async def _save_result(
    message_id: uuid.UUID,
    collector: StreamCollector,
    *,
    latency_ms: int,
    error: str | None,
) -> None:
    """Save the result with a separate database session.

    Not the request's session: by now it may already be closed, and holding it
    open for the whole stream would occupy a pooled connection.

    Errors while saving are swallowed and only logged — the SSE stream is almost
    done, and raising here would only make the user lose the answer they just
    read on screen.
    """
    from app.db.models.message import Message  # avoids an import cycle at startup

    try:
        async with get_sessionmaker()() as db:
            message = await db.get(Message, message_id)
            if message is None:
                logger.warning("Message %s not found when saving the result", message_id)
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
        logger.exception("Could not save the result for message %s", message_id)
