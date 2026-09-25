"use client";

import { Markdown } from "@/components/chat/markdown";
import { ThinkingBlock } from "@/components/chat/thinking-block";
import { ToolCallCard, type ToolCallView } from "@/components/chat/tool-call-card";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/chat";

interface Props {
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCallView[];
  /** What the model reasoned through before answering. */
  thinking?: string;
  /** Still thinking — show the waiting animation. */
  isThinking?: boolean;
  /** Seconds spent thinking, once finished. */
  thinkingSeconds?: number | null;
  /** Receiving text — show a blinking caret at the end. */
  streaming?: boolean;
  error?: string | null;
  meta?: string | null;
}

/** Converts a database record into the tool card view shape. */
export function toolCallsOf(message: Message): ToolCallView[] {
  return message.tool_calls.map((tc) => ({
    name: tc.name,
    args: tc.args,
    status: tc.status,
    result: tc.result,
    error: tc.error,
    durationMs: tc.duration_ms,
  }));
}

export function MessageItem({
  role,
  content,
  toolCalls = [],
  thinking = "",
  isThinking = false,
  thinkingSeconds = null,
  streaming = false,
  error = null,
  meta = null,
}: Props) {
  if (role === "user") {
    return (
      <div className="k8s-fade-in flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-[var(--primary)] px-4 py-2.5 text-sm text-[var(--primary-foreground)]">
          {content}
        </div>
      </div>
    );
  }

  // The assistant has picked up the request but has nothing to show yet: don't
  // let the screen sit still.
  const isWaiting = streaming && !thinking && !content && toolCalls.length === 0;

  return (
    <div className="space-y-2">
      {(thinking || isThinking) && (
        <ThinkingBlock content={thinking} isThinking={isThinking} seconds={thinkingSeconds} />
      )}

      {toolCalls.length > 0 && (
        <div className="space-y-1.5">
          {toolCalls.map((tc, i) => (
            <ToolCallCard key={`${tc.name}-${i}`} call={tc} />
          ))}
        </div>
      )}

      {isWaiting && (
        <div className="flex items-center gap-2 text-xs">
          <span className="k8s-shimmer font-medium">Connecting to the assistant</span>
          <span aria-hidden className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="k8s-dot-bounce size-1 rounded-full bg-[var(--muted-foreground)]"
                style={{ animationDelay: `${i * 0.16}s` }}
              />
            ))}
          </span>
        </div>
      )}

      {content && (
        <Markdown className={cn("break-words", streaming && "k8s-typing")}>
          {content}
        </Markdown>
      )}

      {error && (
        <p
          className={cn(
            "k8s-fade-in rounded-md bg-[var(--destructive)]/10 px-3 py-2 text-sm",
            "text-[var(--destructive)]",
          )}
        >
          {error}
        </p>
      )}

      {meta && <p className="text-[11px] text-[var(--muted-foreground)]">{meta}</p>}
    </div>
  );
}
