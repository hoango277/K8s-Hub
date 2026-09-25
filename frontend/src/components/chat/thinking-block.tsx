"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface Props {
  /** Reasoning received so far. */
  content: string;
  /** Still thinking, or done. */
  isThinking: boolean;
  /** Seconds spent thinking, only once finished. */
  seconds?: number | null;
}

/**
 * Block showing what the model reasoned through before answering.
 *
 * Three rules, in order of importance:
 *
 *   1. It must NEVER look like the answer. Grey, italic, indented, clearly
 *      labelled. Reasoning contains guesses and even wrong conclusions the
 *      model rejects a moment later — a reader mistaking it for the conclusion
 *      is worse than not showing it at all.
 *   2. Open while thinking, collapse automatically when done. While waiting,
 *      the user needs to see that something is happening; once the answer is
 *      there, the reasoning is just clutter. Anyone who wants it can expand it.
 *   3. If the user opens/closes it themselves, respect that and stop
 *      auto-collapsing.
 */
export function ThinkingBlock({ content, isThinking, seconds = null }: Props) {
  const [open, setOpen] = useState(isThinking);
  const userToggled = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Collapse once thinking is done — unless the user has toggled it.
  useEffect(() => {
    if (!userToggled.current) setOpen(isThinking);
  }, [isThinking]);

  // While thinking, stick to the bottom so the newest line is always visible.
  useEffect(() => {
    if (!isThinking || !open) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [content, isThinking, open]);

  if (!content && !isThinking) return null;

  const label = isThinking
    ? "Thinking"
    : seconds != null
      ? `Thought for ${seconds.toFixed(1)} seconds`
      : "Assistant's reasoning";

  return (
    <div className="k8s-fade-in rounded-lg border border-dashed bg-[var(--muted)]/40">
      <button
        type="button"
        onClick={() => {
          userToggled.current = true;
          setOpen((v) => !v);
        }}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span aria-hidden className="text-xs text-[var(--muted-foreground)]">
          ✻
        </span>

        <span
          className={cn(
            "text-xs font-medium",
            isThinking ? "k8s-shimmer" : "text-[var(--muted-foreground)]",
          )}
        >
          {label}
        </span>

        {isThinking && (
          <span aria-hidden className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="k8s-dot-bounce size-1 rounded-full bg-[var(--muted-foreground)]"
                style={{ animationDelay: `${i * 0.16}s` }}
              />
            ))}
          </span>
        )}

        {content && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            {open ? "hide" : "show"}
          </span>
        )}
      </button>

      <div className="k8s-collapse" data-open={open && Boolean(content)}>
        <div>
          <div
            ref={scrollRef}
            className={cn(
              "max-h-56 overflow-y-auto whitespace-pre-wrap px-3 pb-3 pl-7",
              "text-xs italic leading-relaxed text-[var(--muted-foreground)]",
            )}
          >
            {content}
          </div>
        </div>
      </div>
    </div>
  );
}
