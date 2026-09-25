/**
 * Streaming events received from the backend over SSE.
 *
 * ===========================================================================
 *  CONTRACT BETWEEN BACKEND AND FRONTEND
 *  This file must match `backend/app/schemas/events.py` one-to-one.
 *  Changing it here REQUIRES changing the other side and telling the team.
 * ===========================================================================
 *
 * Shared by two streams: command conversations and diagnosis progress.
 */

export type ToolStatus = "ok" | "error";
export type StepStatus = "running" | "done" | "error";
export type DangerLevel = "safe" | "caution" | "dangerous";

/** Fields common to every event. */
export interface BaseEvent {
  /**
   * Increasing sequence number within a stream, starting at 1.
   * Used to detect lost events and resume after a disconnect
   * (sent back via the Last-Event-ID header).
   */
  seq: number;
}

/** A chunk of the answer text. Concatenate chunks in order. */
export interface TokenEvent extends BaseEvent {
  type: "token";
  content: string;
}

/**
 * A chunk of the model's REASONING — what it thinks before answering.
 *
 * Must be displayed fully separate from the answer and be obviously
 * reasoning: it contains guesses and wrong conclusions the model later
 * rejects itself. Not every provider sends this event type.
 */
export interface ThinkingEvent extends BaseEvent {
  type: "thinking";
  content: string;
}

/**
 * Progress report for a processing step.
 * If `key` matches a step received earlier, UPDATE the existing line rather
 * than adding a new one — that's how running → done can change in place.
 */
export interface StepEvent extends BaseEvent {
  type: "step";
  /** Step code, stable within a stream. E.g. "collect_logs" */
  key: string;
  /** Text shown to the user */
  label: string;
  status: StepStatus;
}

/** The assistant starts calling a tool. */
export interface ToolCallStartEvent extends BaseEvent {
  type: "tool_call_start";
  /** Call id, used to pair with tool_call_end */
  id: string;
  /** Tool name, e.g. "list_resources" */
  name: string;
  args: Record<string, unknown>;
}

/** The tool finished. `id` matches the corresponding tool_call_start. */
export interface ToolCallEndEvent extends BaseEvent {
  type: "tool_call_end";
  id: string;
  status: ToolStatus;
  duration_ms: number;
  /** TRUNCATED result for display. See Langfuse for the full version. */
  result?: string;
  /** Only present when status === "error" */
  error?: string;
}

/** One step in the plan the assistant proposes. */
export interface PlanStep {
  order: number;
  description: string;
}

/** The plan the assistant intends to carry out, sent BEFORE asking for approval. */
export interface PlanEvent extends BaseEvent {
  type: "plan";
  steps: PlanStep[];
  summary?: string;
}

/**
 * The stream pauses waiting for a human to approve.
 * After this event the SSE stream does NOT end; it hangs waiting.
 * The client calls POST /approvals/{approval_id}/approve|reject in a separate request.
 */
export interface ApprovalRequiredEvent extends BaseEvent {
  type: "approval_required";
  approval_id: string;
  /** E.g. "Scale api from 1 to 3 replicas" */
  summary: string;
  /** Before/after comparison, as a unified YAML diff */
  diff: string;
  danger_level: DangerLevel;
  /** Output of a dry run that doesn't take effect */
  dry_run_output?: string;
}

/** The user has decided. Sent right before the stream continues. */
export interface ApprovalResolvedEvent extends BaseEvent {
  type: "approval_resolved";
  approval_id: string;
  approved: boolean;
  decided_by?: string;
  /** Reason, when rejected */
  reason?: string;
}

/** Result of re-checking after an action was applied to the cluster. */
export interface VerifyResultEvent extends BaseEvent {
  type: "verify_result";
  ok: boolean;
  /** E.g. "3/3 replicas ready after 12 seconds" */
  message: string;
}

/** An error occurred. If retryable === false the stream ends after this event. */
export interface ErrorEvent extends BaseEvent {
  type: "error";
  /** E.g. "llm_timeout", "guardrail_blocked", "k8s_forbidden" */
  code: string;
  message: string;
  retryable: boolean;
}

/** The stream ended normally. Always the last event. */
export interface DoneEvent extends BaseEvent {
  type: "done";
  /** Record id in the database */
  message_id?: string;
  /** Langfuse trace id, for linking to the details */
  trace_id?: string;
}

/**
 * Keep-alive heartbeat, sent every ~15 seconds when there's nothing else to send.
 * Without it, proxies cut idle connections. The client ignores this event.
 */
export interface HeartbeatEvent extends BaseEvent {
  type: "heartbeat";
}

export type AgentEvent =
  | TokenEvent
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
  | HeartbeatEvent;

export type AgentEventType = AgentEvent["type"];

/** Get the exact event type by `type`. E.g. `EventOf<"token">` */
export type EventOf<K extends AgentEventType> = Extract<AgentEvent, { type: K }>;

/** Every event type — used to register a listener per type. */
export const AGENT_EVENT_TYPES = [
  "token",
  "thinking",
  "step",
  "tool_call_start",
  "tool_call_end",
  "plan",
  "approval_required",
  "approval_resolved",
  "verify_result",
  "error",
  "done",
  "heartbeat",
] as const satisfies readonly AgentEventType[];

/**
 * Narrow the type when handling an event.
 *
 * The chat panel uses `switch` so it doesn't need this, but the upcoming
 * diagnosis screen only cares about a few event types — filtering with this
 * function is neater there.
 */
export function isEvent<K extends AgentEventType>(
  event: AgentEvent,
  type: K,
): event is EventOf<K> {
  return event.type === type;
}

/** Parse the `data` of an SSE message. Returns null if malformed. */
export function parseAgentEvent(raw: string): AgentEvent | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "type" in parsed &&
      typeof (parsed as { type: unknown }).type === "string" &&
      (AGENT_EVENT_TYPES as readonly string[]).includes(
        (parsed as { type: string }).type,
      )
    ) {
      return parsed as AgentEvent;
    }
    return null;
  } catch {
    return null;
  }
}
