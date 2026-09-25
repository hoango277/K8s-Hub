"use client";

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { API_BASE } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import { streamAgentEvents } from "@/lib/sse";
import type { AgentEvent } from "@/types/events";

/** A tool call in progress, built up from the start and end events. */
export interface LiveToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  result?: string | null;
  error?: string | null;
  durationMs?: number | null;
}

/** The turn currently streaming — not yet in the database. */
export interface LiveTurn {
  /** The question just sent, shown right away so the user gets instant feedback. */
  question: string;
  content: string;

  /** The model's own reasoning. Empty if the provider doesn't expose it. */
  thinking: string;
  /** Total time spent thinking, in milliseconds. */
  thinkingMs: number;
  /**
   * When the current thinking phase started; null means not thinking.
   * A turn can think in several phases: think -> call a tool -> think again.
   */
  thinkingSince: number | null;

  toolCalls: LiveToolCall[];
  status: "streaming" | "error" | "done";
  error: { code: string; message: string; retryable: boolean } | null;
  traceId: string | null;
}

function startTurn(question: string): LiveTurn {
  return {
    question,
    content: "",
    thinking: "",
    thinkingMs: 0,
    thinkingSince: null,
    toolCalls: [],
    status: "streaming",
    error: null,
    traceId: null,
  };
}

/**
 * End the current thinking phase and add up its duration.
 *
 * Call on any sign that the model has finished thinking: it starts emitting
 * text, calls a tool, or the stream ends. Without finalizing, the "Thinking"
 * line keeps pulsing forever even after the answer has appeared.
 */
function finalizeThinking(t: LiveTurn): LiveTurn {
  if (t.thinkingSince === null) return t;
  return {
    ...t,
    thinkingMs: t.thinkingMs + (Date.now() - t.thinkingSince),
    thinkingSince: null,
  };
}

/**
 * Rebuild the turn's state from one event.
 *
 * Kept as a pure function (no React) so it's easy to follow and testable: feed
 * in a sequence of events, get exactly one state out.
 */
function applyEvent(t: LiveTurn, ev: AgentEvent): LiveTurn {
  switch (ev.type) {
    case "thinking":
      return {
        ...t,
        thinking: t.thinking + ev.content,
        thinkingSince: t.thinkingSince ?? Date.now(),
      };

    case "token":
      return { ...finalizeThinking(t), content: t.content + ev.content };

    case "tool_call_start":
      return {
        ...finalizeThinking(t),
        toolCalls: [
          ...t.toolCalls,
          { id: ev.id, name: ev.name, args: ev.args, status: "running" },
        ],
      };

    case "tool_call_end":
      return {
        ...t,
        toolCalls: t.toolCalls.map((tc) =>
          tc.id === ev.id
            ? {
                ...tc,
                status: ev.status,
                result: ev.result,
                error: ev.error,
                durationMs: ev.duration_ms,
              }
            : tc,
        ),
      };

    case "error":
      return {
        ...finalizeThinking(t),
        status: "error",
        error: { code: ev.code, message: ev.message, retryable: ev.retryable },
      };

    case "done":
      return {
        ...finalizeThinking(t),
        status: t.status === "error" ? "error" : "done",
        // The backend drops null fields from the payload entirely, so this can
        // be undefined, not just null.
        traceId: ev.trace_id ?? null,
      };

    default:
      // heartbeat, step, plan, approval_*: not used by the chat panel yet.
      return t;
  }
}

/** Provider/model override sent with a question. */
export interface LlmSelection {
  provider?: string | null;
  model?: string | null;
}

/**
 * Send a question and rebuild the answer from the event stream.
 *
 * When the stream ends, the hook reloads the thread from the server BEFORE
 * clearing the live copy on screen. Doing it the other way round — clear
 * first, reload after — leaves a moment where the screen is empty, which looks
 * like the answer just vanished.
 */
export function useChatStream(threadId: string | null, selection: LlmSelection = {}) {
  const qc = useQueryClient();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const isStreaming = live?.status === "streaming";

  const send = useCallback(
    async (question: string) => {
      if (!threadId || isStreaming) return;

      const controller = new AbortController();
      abortRef.current = controller;
      setLive(startTurn(question));

      try {
        for await (const ev of streamAgentEvents(
          `${API_BASE}/chat/threads/${threadId}/stream`,
          // Send along the user's choice. If empty, the backend uses the
          // system configuration.
          { content: question, provider: selection.provider, model: selection.model },
          { signal: controller.signal },
        )) {
          setLive((t) => (t ? applyEvent(t, ev) : t));
        }
      } catch (err) {
        // The user pressing stop is not an error.
        if (!controller.signal.aborted) {
          setLive((t) =>
            t
              ? {
                  ...finalizeThinking(t),
                  status: "error",
                  error: {
                    code: "network",
                    message:
                      err instanceof Error ? err.message : "Lost connection to the server",
                    retryable: true,
                  },
                }
              : t,
          );
        }
      } finally {
        abortRef.current = null;

        // The server has finished saving (even on error or mid-stream stop);
        // reload so the screen shows exactly what is in the database.
        await qc.invalidateQueries({ queryKey: qk.threads.detail(threadId) });
        await qc.invalidateQueries({ queryKey: qk.threads.lists });
        setLive(null);
      }
    },
    [threadId, isStreaming, qc, selection.provider, selection.model],
  );

  /** Stop mid-stream. What the assistant already said is still saved by the server. */
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { live, isStreaming, send, stop };
}
