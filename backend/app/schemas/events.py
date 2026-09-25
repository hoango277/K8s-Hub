"""Streaming events pushed from the backend to the client over SSE.

===========================================================================
 CONTRACT BETWEEN BACKEND AND FRONTEND
 This file must match `frontend/src/types/events.ts` 1-to-1.
 Changing it here REQUIRES changing the other side and telling the team.
===========================================================================

Shared by two flows:
  - Command conversation  (app/modules/nl_command)
  - Diagnosis progress    (app/modules/rca)

How events are packed onto the wire: see `to_sse()` at the end of the file.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# --------------------------------------------------------------------------
# Reusable types
# --------------------------------------------------------------------------

ToolStatus: TypeAlias = Literal["ok", "error"]
StepStatus: TypeAlias = Literal["running", "done", "error"]
DangerLevel: TypeAlias = Literal["safe", "caution", "dangerous"]


class BaseEvent(BaseModel):
    """The part shared by every event."""

    model_config = ConfigDict(extra="forbid")

    seq: int = Field(
        default=0,
        description=(
            "Increasing sequence number within one stream, starting at 1. "
            "The client uses it to detect lost events and to resume after a "
            "disconnect (sent back via the Last-Event-ID header). Assigned by EventStream."
        ),
    )


# --------------------------------------------------------------------------
# Event types
# --------------------------------------------------------------------------


class TokenEvent(BaseEvent):
    """A chunk of the answer text. The client joins the chunks in order."""

    type: Literal["token"] = "token"
    content: str


class ThinkingEvent(BaseEvent):
    """A chunk of the model's REASONING, not the answer.

    This is what the model thinks before speaking — what it is weighing, what
    it plans to look up. Very worth showing in operations: the on-call
    engineer can see which direction the assistant is heading, and catch it
    early when it misunderstands the question.

    Displayed SEPARATELY from the answer and must be immediately recognizable
    as reasoning. Mixing the two is dangerous: reasoning often contains guesses
    and even wrong conclusions the model rejects right afterwards.

    Not every provider has it. If there is none, simply no events of this type
    are sent.
    """

    type: Literal["thinking"] = "thinking"
    content: str


class StepEvent(BaseEvent):
    """Reports the progress of a processing step.

    Mainly used for diagnosis ("Collecting logs..."), but the command flow can
    use it too. If `key` matches a step sent earlier, the client UPDATES the
    old line instead of adding a new one — that is what allows the status to
    change from running → done.
    """

    type: Literal["step"] = "step"
    key: str = Field(description="Step key, stable within one stream. E.g. 'collect_logs'")
    label: str = Field(description="Text shown to the user")
    status: StepStatus = "running"


class ToolCallStartEvent(BaseEvent):
    """The assistant starts calling a tool."""

    type: Literal["tool_call_start"] = "tool_call_start"
    id: str = Field(description="Call id, used to pair with tool_call_end")
    name: str = Field(description="Tool name, e.g. 'list_resources'")
    args: dict[str, Any] = Field(default_factory=dict)


class ToolCallEndEvent(BaseEvent):
    """The tool finished. `id` must match the corresponding tool_call_start."""

    type: Literal["tool_call_end"] = "tool_call_end"
    id: str
    status: ToolStatus
    duration_ms: int
    result: str | None = Field(
        default=None,
        description="TRUNCATED result for display. See Langfuse for the full version.",
    )
    error: str | None = Field(default=None, description="Only present when status='error'")


class PlanStep(BaseModel):
    """One step in the plan the assistant proposes."""

    model_config = ConfigDict(extra="forbid")

    order: int
    description: str


class PlanEvent(BaseEvent):
    """The plan the assistant intends to carry out, sent BEFORE asking for approval."""

    type: Literal["plan"] = "plan"
    steps: list[PlanStep]
    summary: str | None = None


class ApprovalRequiredEvent(BaseEvent):
    """The stream pauses to wait for human approval.

    After this event the SSE stream does NOT end but hangs waiting. The client
    calls POST /approvals/{approval_id}/approve|reject in a separate request.
    """

    type: Literal["approval_required"] = "approval_required"
    approval_id: str
    summary: str = Field(description="E.g. 'Scale api replicas from 1 to 3'")
    diff: str = Field(description="Before/after comparison, as a unified YAML diff")
    danger_level: DangerLevel = "caution"
    dry_run_output: str | None = Field(
        default=None, description="Dry-run output (not actually applied)"
    )


class ApprovalResolvedEvent(BaseEvent):
    """The user has decided. Sent right before the stream resumes."""

    type: Literal["approval_resolved"] = "approval_resolved"
    approval_id: str
    approved: bool
    decided_by: str | None = None
    reason: str | None = Field(default=None, description="Reason when rejected")


class VerifyResultEvent(BaseEvent):
    """Result of re-checking after an action has been applied to the cluster."""

    type: Literal["verify_result"] = "verify_result"
    ok: bool
    message: str = Field(description="E.g. '3/3 replicas ready after 12 seconds'")


class ErrorEvent(BaseEvent):
    """An error occurred. If retryable=False the stream ends after this event."""

    type: Literal["error"] = "error"
    code: str = Field(description="E.g. 'llm_timeout', 'guardrail_blocked', 'k8s_forbidden'")
    message: str
    retryable: bool = False


class DoneEvent(BaseEvent):
    """The stream ended normally. Always the last event."""

    type: Literal["done"] = "done"
    message_id: str | None = Field(default=None, description="Record id in the database")
    trace_id: str | None = Field(
        default=None, description="Langfuse trace id, so the client can open a link to the details"
    )


class HeartbeatEvent(BaseEvent):
    """Keep-alive ping, sent every ~15 seconds when there is nothing else to send.

    Without it, proxies (nginx, ingress) cut idle connections.
    The client ignores this event.
    """

    type: Literal["heartbeat"] = "heartbeat"


# --------------------------------------------------------------------------
# Union + helpers
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
    """Pack an event into an SSE frame for `sse_starlette.EventSourceResponse`.

    The event is named after its `type` so the client can listen to each kind
    separately (addEventListener('token', ...)) as well as to all of them.
    """
    return {
        "event": event.type,  # type: ignore[attr-defined]
        "id": str(event.seq),
        "data": event.model_dump_json(exclude_none=True),
    }


class EventStream:
    """Numbers and packs events.

    Create a new instance for each reply:

        stream = EventStream()
        yield stream.emit(TokenEvent(content="Hel"))
        yield stream.emit(TokenEvent(content="lo"))
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
