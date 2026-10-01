"use client";

import Link from "next/link";
import { Info } from "lucide-react";

import { Markdown } from "@/components/chat/markdown";
import { ActivityBlock, type ThoughtStep } from "@/components/chat/activity-block";
import { ApprovalCard } from "@/components/chat/approval-card";
import { type ToolCallView } from "@/components/chat/tool-call-card";
import { WaitingIndicator } from "@/components/chat/waiting-indicator";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/chat";

interface Props {
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCallView[];
  /** What the model reasoned through, split where tool calls happened. */
  thinkingSteps?: ThoughtStep[];
  /** Still thinking — show the waiting animation. */
  isThinking?: boolean;
  /** Seconds spent thinking, once finished. */
  thinkingSeconds?: number | null;
  /** Receiving text — show a blinking caret at the end. */
  streaming?: boolean;
  error?: string | null;
  meta?: string | null;
  /** Stored answer still being written on the server (not streamed to this tab). */
  inProgress?: boolean;
  /** When the live turn started, for the waiting indicator's counter. */
  startedAt?: number | null;
}

/** The stored reasoning as ordered steps; older messages only have one blob. */
export function thoughtsOf(message: Message): ThoughtStep[] {
  if (message.reasoning_steps?.length) {
    return message.reasoning_steps.map((s) => ({ text: s.text, atTool: s.at_tool }));
  }
  return message.reasoning ? [{ text: message.reasoning, atTool: 0 }] : [];
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
    approvalId: tc.approval_id ?? null,
  }));
}

/** What the assistant is doing before the first word of the answer. */
function waitingLabel(toolCalls: ToolCallView[], isThinking: boolean): string {
  const running = toolCalls.find((tc) => tc.status === "running");
  if (running) return `Running ${running.name}`;
  if (isThinking) return "Thinking";
  if (toolCalls.length > 0) return "Reading the results";
  return "Connecting to the assistant";
}

export function MessageItem({
  role,
  content,
  toolCalls = [],
  thinkingSteps = [],
  isThinking = false,
  thinkingSeconds = null,
  streaming = false,
  error = null,
  meta = null,
  inProgress = false,
  startedAt = null,
}: Props) {
  // A note from K8s-Hub itself (e.g. a proposed change was approved and ran):
  // neither the user nor the assistant said it, so it reads as a system line.
  if (role === "system") {
    return (
      <div className="k8s-fade-in flex justify-center">
        <p
          role="note"
          className="flex max-w-[90%] items-start gap-2 whitespace-pre-wrap break-words rounded-lg border bg-[var(--muted)]/50 px-3 py-2 text-xs leading-relaxed text-[var(--muted-foreground)]"
        >
          <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          <span>{content}</span>
        </p>
      </div>
    );
  }

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
  const isWaiting = streaming && !isThinking && thinkingSteps.length === 0 && !content && toolCalls.length === 0;
  const approvals = toolCalls.filter((tc) => tc.approvalId);

  return (
    <div className="space-y-2">
      <ActivityBlock
        steps={thinkingSteps}
        toolCalls={toolCalls}
        isThinking={isThinking}
        streaming={streaming}
        thinkingSeconds={thinkingSeconds}
      />

      {/* Proposed changes stay visible outside the collapsed activity: they
          are the one thing here that asks the reader to act. */}
      {approvals.map((tc) => (
        <ApprovalCard key={tc.approvalId} approvalId={tc.approvalId!} compact />
      ))}

      {inProgress && (
        <p role="status" className="flex items-start gap-2 rounded-lg border border-dashed px-3 py-2 text-xs text-[var(--muted-foreground)]">
          <Spinner className="mt-0.5 size-3.5" />
          <span>
            Still working on this answer on the server. It appears here when it&apos;s done — any change it
            proposes waits in <Link href="/approvals" className="underline underline-offset-2">Approvals</Link>{" "}
            and nothing runs before an engineer approves it.
          </span>
        </p>
      )}

      {streaming && !content && (
        <WaitingIndicator
          label={waitingLabel(toolCalls, isThinking)}
          startedAt={startedAt}
          skeleton={isWaiting}
        />
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
