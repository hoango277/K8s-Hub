"use client";

import { useId, useState } from "react";
import { ChevronRight, Sparkles, Wrench } from "lucide-react";

import { ToolCallDetails, type ToolCallView } from "@/components/chat/tool-call-card";
import { cn } from "@/lib/utils";

export interface ThoughtStep {
  text: string;
  /** How many tool calls came before this thought. */
  atTool: number;
}

type Item = { kind: "thought"; text: string } | { kind: "tool"; call: ToolCallView };

/** Thoughts and tool calls in the order they happened. */
function timeline(steps: ThoughtStep[], calls: ToolCallView[]): Item[] {
  const items: Item[] = [];
  for (let k = 0; k <= calls.length; k++) {
    for (const s of steps) if (s.atTool === k && s.text.trim()) items.push({ kind: "thought", text: s.text });
    if (k < calls.length) items.push({ kind: "tool", call: calls[k] });
  }
  return items;
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

/**
 * Everything the assistant did before (and while) answering — its reasoning
 * and every tool call — as ONE collapsible line.
 *
 * Replaces a reasoning block above a separate card per tool call: a health
 * check calling five tools pushed the answer off the screen, and reasoning
 * made between two calls was lumped into the block at the top, out of order.
 *
 * Collapsed by default, also while streaming: the header line says what is
 * happening right now ("Running list_pods"), which is all most people need.
 * Expanded, it shows thought → tool → thought in order; reasoning stays grey
 * and italic so it never reads like the answer.
 */
export function ActivityBlock({
  steps,
  toolCalls,
  isThinking = false,
  streaming = false,
  thinkingSeconds = null,
}: {
  steps: ThoughtStep[];
  toolCalls: ToolCallView[];
  isThinking?: boolean;
  streaming?: boolean;
  thinkingSeconds?: number | null;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const items = timeline(steps, toolCalls);
  if (items.length === 0 && !isThinking) return null;

  const running = toolCalls.find((c) => c.status === "running");
  const failed = toolCalls.filter((c) => c.status === "error").length;
  const busy = streaming && (isThinking || Boolean(running));

  let label: string;
  if (busy) {
    // The live phase (with animation) is the WaitingIndicator below; this
    // header just counts, so two animations don't say the same thing.
    label = toolCalls.length ? `Working · ${plural(toolCalls.length, "tool")} so far` : "Reasoning so far";
  } else {
    const parts: string[] = [];
    if (thinkingSeconds != null && thinkingSeconds > 0) parts.push(`Thought for ${thinkingSeconds.toFixed(1)}s`);
    else if (steps.some((s) => s.text.trim())) parts.push("Reasoned");
    if (toolCalls.length) parts.push(`used ${plural(toolCalls.length, "tool")}`);
    label = parts.join(" · ") || "Worked on it";
    label = label.charAt(0).toUpperCase() + label.slice(1);
  }

  return (
    <div className="k8s-fade-in rounded-lg border border-dashed bg-[var(--muted)]/40 text-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        className="flex min-h-9 w-full items-center gap-2 rounded-lg px-3 py-2 text-left outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        <ChevronRight
          aria-hidden
          className={cn(
            "size-3.5 shrink-0 text-[var(--muted-foreground)] transition-transform motion-reduce:transition-none",
            open && "rotate-90",
          )}
        />
        <span
          className={cn(
            "min-w-0 truncate text-xs font-medium",
            "text-[var(--muted-foreground)]",
          )}
        >
          {label}
        </span>
        {failed > 0 && (
          <span className="shrink-0 text-xs font-medium text-[var(--destructive)]">{failed} failed</span>
        )}
        <span className="ml-auto shrink-0 text-xs text-[var(--muted-foreground)]">{open ? "hide" : "show"}</span>
      </button>

      <div id={panelId} className="k8s-collapse" data-open={open}>
        <div>
          <ol className="space-y-2 border-t px-3 py-3">
            {items.map((item, i) =>
              item.kind === "thought" ? (
                <li key={i} className="flex gap-2">
                  <Sparkles aria-hidden className="mt-0.5 size-3.5 shrink-0 text-[var(--muted-foreground)]" />
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium text-[var(--muted-foreground)]">Thought</p>
                    <p className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words text-xs italic leading-relaxed text-[var(--muted-foreground)]">
                      {item.text}
                    </p>
                  </div>
                </li>
              ) : (
                <li key={i} className="flex gap-2">
                  <Wrench aria-hidden className="mt-2.5 size-3.5 shrink-0 text-[var(--muted-foreground)]" />
                  <div className="min-w-0 flex-1">
                    <ToolCallDetails call={item.call} />
                  </div>
                </li>
              ),
            )}
            {isThinking && items.length === 0 && (
              <li className="text-xs italic text-[var(--muted-foreground)]">Thinking…</li>
            )}
          </ol>
        </div>
      </div>
    </div>
  );
}
