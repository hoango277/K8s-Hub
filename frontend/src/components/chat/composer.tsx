"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Square } from "lucide-react";

import { cn } from "@/lib/utils";

interface Props {
  onSend: (content: string) => void;
  onStop: () => void;
  isStreaming: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** Slot for the provider and model pickers, inside the same frame as the input. */
  toolbar?: ReactNode;
}

const MAX_HEIGHT = 200;

/**
 * The question input.
 *
 * The textarea, model picker and send button share ONE bordered frame instead
 * of three separate stacked blocks. They are always used together in a single
 * action, so grouping them keeps the eye from jumping between three regions.
 */
export function Composer({
  onSend,
  onStop,
  isStreaming,
  disabled = false,
  placeholder = "Ask about your cluster, or describe what you need done…",
  toolbar,
}: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // The textarea grows with its content up to a limit, then scrolls.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [text]);

  const canSend = Boolean(text.trim()) && !disabled && !isStreaming;

  function submit() {
    if (!canSend) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            "rounded-2xl border bg-[var(--background)] shadow-sm transition",
            "focus-within:border-[var(--ring)] focus-within:shadow-md",
          )}
        >
          <textarea
            ref={ref}
            rows={1}
            value={text}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter inserts a newline. While typing with an
              // IME (e.g. Vietnamese input methods), Enter picks a candidate —
              // don't hijack that key.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            className={cn(
              "w-full resize-none bg-transparent px-4 pt-3 text-sm leading-relaxed",
              "outline-none placeholder:text-[var(--muted-foreground)]",
              "disabled:opacity-50",
            )}
          />

          <div className="flex items-center gap-2 px-2 pb-2 pt-1">
            {toolbar}

            {isStreaming ? (
              <button
                type="button"
                onClick={onStop}
                title="Stop responding"
                className={cn(
                  "ml-auto flex size-8 shrink-0 items-center justify-center rounded-full",
                  "border transition hover:bg-[var(--accent)]",
                )}
              >
                <Square aria-hidden className="size-3.5 fill-current" />
                <span className="sr-only">Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={!canSend}
                title="Send (Enter)"
                className={cn(
                  "ml-auto flex size-8 shrink-0 items-center justify-center rounded-full",
                  "bg-[var(--primary)] text-[var(--primary-foreground)] transition",
                  "hover:opacity-90 disabled:opacity-30",
                )}
              >
                <ArrowUp aria-hidden className="size-4" />
                <span className="sr-only">Send</span>
              </button>
            )}
          </div>
        </div>

        <p className="mt-1.5 px-1 text-center text-[11px] text-[var(--muted-foreground)]">
          The assistant only looks things up — every change to the cluster needs human approval.
        </p>
      </div>
    </div>
  );
}
