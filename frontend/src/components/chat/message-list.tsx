"use client";

import { useEffect, useRef } from "react";
import { BookOpen, Bot, Cpu, ShieldCheck } from "lucide-react";

import { MessageItem, toolCallsOf } from "@/components/chat/message-item";
import type { LiveTurn } from "@/hooks/use-chat-stream";
import type { Message } from "@/types/chat";

interface Props {
  messages: Message[];
  live: LiveTurn | null;
  toolNames: string[];
  /** Clicking a suggestion sends it right away. Omit to hide suggestions. */
  onSuggestion?: (question: string) => void;
}

// Only suggest questions the assistant CAN ANSWER RIGHT NOW with the tools it
// has (`system_info`, `current_time`) or from general knowledge. Suggesting
// "which pods are failing?" before there is a cluster lookup tool promises
// something the system can't do yet — same principle as the system prompt in
// nl_command/prompts.
const SUGGESTIONS = [
  { icon: Cpu, question: "Which AI model is the system using?" },
  { icon: ShieldCheck, question: "What does the current execution mode let me do on the cluster?" },
  { icon: BookOpen, question: "Explain CrashLoopBackOff and the usual steps to fix it" },
  { icon: BookOpen, question: "When should I use a StatefulSet instead of a Deployment?" },
];

function caption(m: Message): string | null {
  if (m.role !== "assistant") return null;
  const parts: string[] = [];
  if (m.model) parts.push(m.model);
  if (m.latency_ms != null) parts.push(`${(m.latency_ms / 1000).toFixed(1)}s`);
  return parts.length ? parts.join(" · ") : null;
}

export function MessageList({ messages, live, toolNames, onSuggestion }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  // Always stick to the bottom when new text arrives. Content lengths are the
  // dependencies so that every chunk received pulls the view down with it.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [
    messages.length,
    live?.content.length,
    live?.thinking.length,
    live?.toolCalls.length,
  ]);

  const isEmpty = messages.length === 0 && !live;

  if (isEmpty) {
    return (
      <div className="flex min-h-full items-center justify-center px-6 py-10">
        <div className="w-full max-w-2xl">
          <div className="text-center">
            <span className="mx-auto flex size-12 items-center justify-center rounded-xl bg-[var(--primary)] text-[var(--primary-foreground)] shadow-sm">
              <Bot aria-hidden className="size-6" />
            </span>
            <h2 className="mt-4 text-xl font-semibold tracking-tight">How can I help?</h2>
            <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-[var(--muted-foreground)]">
              Ask about cluster health, the cause of an incident, or describe what you want to
              do. Every change to the cluster goes through approval.
            </p>
          </div>

          {onSuggestion && (
            <ul className="mt-8 grid gap-2 sm:grid-cols-2">
              {SUGGESTIONS.map(({ icon: Icon, question }) => (
                <li key={question}>
                  <button
                    type="button"
                    onClick={() => onSuggestion(question)}
                    className="flex h-full w-full items-start gap-3 rounded-lg border bg-[var(--background)] p-3 text-left text-sm outline-none transition hover:border-[var(--ring)] hover:bg-[var(--accent)]/50 focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                  >
                    <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)]" />
                    <span>{question}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {toolNames.length > 0 && (
            <p className="mt-6 text-center text-xs text-[var(--muted-foreground)]">
              Available tools:{" "}
              {toolNames.map((t) => (
                <code key={t} className="mx-0.5 rounded bg-[var(--muted)] px-1.5 py-0.5">
                  {t}
                </code>
              ))}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      {messages.map((m) => (
        <MessageItem
          key={m.id}
          role={m.role}
          content={m.content}
          thinking={m.reasoning ?? ""}
          toolCalls={toolCallsOf(m)}
          error={m.status === "error" ? m.error : null}
          meta={caption(m)}
        />
      ))}

      {live && (
        <>
          <MessageItem role="user" content={live.question} />
          <MessageItem
            role="assistant"
            content={live.content}
            thinking={live.thinking}
            isThinking={live.thinkingSince !== null}
            thinkingSeconds={live.thinkingMs > 0 ? live.thinkingMs / 1000 : null}
            toolCalls={live.toolCalls}
            streaming={live.status === "streaming"}
            error={live.error?.message ?? null}
          />
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
