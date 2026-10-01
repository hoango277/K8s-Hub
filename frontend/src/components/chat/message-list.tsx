"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { ArrowRight, BookOpen, Bot, Cpu, Gauge, HeartPulse, ShieldCheck, Waypoints } from "lucide-react";

import { MessageItem, thoughtsOf, toolCallsOf } from "@/components/chat/message-item";
import type { LiveTurn } from "@/hooks/use-chat-stream";
import type { Message } from "@/types/chat";

interface Props {
  messages: Message[];
  live: LiveTurn | null;
  toolNames: string[];
  /** Clicking a suggestion sends it right away. Omit to hide suggestions. */
  onSuggestion?: (question: string) => void;
}

// Only suggest questions the assistant CAN ANSWER RIGHT NOW. Each suggestion
// names the tool it needs; one whose tool is switched off or unavailable (e.g.
// no Kubernetes access on a laptop) is skipped, and general-knowledge questions
// fill the rest — suggesting "which pods are failing?" without a pod tool
// promises something the system can't do (same rule as the system prompt).
// kube-system exists on every cluster, so the example works anywhere.
const SUGGESTIONS: { icon: typeof Cpu; question: string; needs?: string }[] = [
  { icon: HeartPulse, question: "Is everything healthy in the kube-system namespace?", needs: "list_pods" },
  { icon: Gauge, question: "Which containers in kube-system are closest to their memory limit?", needs: "pod_metrics" },
  { icon: Waypoints, question: "Are there any failing requests in the last 30 minutes?", needs: "search_traces" },
  { icon: ShieldCheck, question: "What does the current execution mode let me do on the cluster?" },
  { icon: BookOpen, question: "Explain CrashLoopBackOff and the usual steps to fix it" },
  { icon: Cpu, question: "Which AI model is the system using?" },
];

function suggestionsFor(toolNames: string[]) {
  const available = new Set(toolNames);
  return SUGGESTIONS.filter((s) => !s.needs || available.has(s.needs)).slice(0, 4);
}

/**
 * The turn being streamed can ALSO be in the stored messages when the thread is
 * re-read mid-stream — e.g. an approval decided in the card writes a note into
 * the conversation and refreshes it. The live view already shows that turn, so
 * drop its stored copy (the question and the "streaming" assistant row).
 */
function withoutLiveTurn(messages: Message[]): Message[] {
  let i = messages.length - 1;
  while (i >= 0 && !(messages[i].role === "assistant" && messages[i].status === "streaming")) i--;
  if (i < 0) return messages;
  const drop = new Set([i]);
  if (i > 0 && messages[i - 1].role === "user") drop.add(i - 1);
  return messages.filter((_, k) => !drop.has(k));
}

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
              {suggestionsFor(toolNames).map(({ icon: Icon, question }) => (
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

          {/* A count and a link, not the raw tool names: the names mean little to a
              user, and 15 of them on one line overflowed the page. */}
          {toolNames.length > 0 && (
            <p className="mt-6 flex flex-wrap items-center justify-center gap-x-2 gap-y-1 text-center text-xs text-[var(--muted-foreground)]">
              <span>
                {toolNames.length} tool{toolNames.length === 1 ? "" : "s"} ready for the assistant
              </span>
              <span aria-hidden>·</span>
              <Link
                href="/skills#tools"
                className="inline-flex items-center gap-1 rounded underline underline-offset-2 outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
              >
                See tools & skills
                <ArrowRight aria-hidden className="size-3" />
              </Link>
            </p>
          )}
        </div>
      </div>
    );
  }

  const stored = live ? withoutLiveTurn(messages) : messages;

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      {stored.map((m) => (
        <MessageItem
          key={m.id}
          role={m.role}
          content={m.content}
          thinkingSteps={thoughtsOf(m)}
          toolCalls={toolCallsOf(m)}
          error={m.status === "error" ? m.error : null}
          inProgress={m.role === "assistant" && m.status === "streaming"}
          meta={caption(m)}
        />
      ))}

      {live && (
        <>
          <MessageItem role="user" content={live.question} />
          <MessageItem
            role="assistant"
            content={live.content}
            thinkingSteps={live.thinkingSteps}
            isThinking={live.thinkingSince !== null}
            thinkingSeconds={live.thinkingMs > 0 ? live.thinkingMs / 1000 : null}
            toolCalls={live.toolCalls}
            streaming={live.status === "streaming"}
            startedAt={live.startedAt}
            error={live.error?.message ?? null}
          />
        </>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
