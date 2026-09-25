"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

export interface ToolCallView {
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  result?: string | null;
  error?: string | null;
  durationMs?: number | null;
}

const STATUS_LABEL: Record<ToolCallView["status"], string> = {
  running: "running",
  ok: "done",
  error: "failed",
};

function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** Spinner while the tool is running, a tick/cross once it finishes. */
function StatusIcon({ status }: { status: ToolCallView["status"] }) {
  if (status === "running") {
    return (
      <span
        aria-hidden
        className={cn(
          "k8s-spin size-3 shrink-0 rounded-full border-[1.5px] border-current",
          "border-t-transparent text-amber-500",
        )}
      />
    );
  }

  return (
    <span
      aria-hidden
      className={cn(
        "flex size-3 shrink-0 items-center justify-center rounded-full text-[8px]",
        "font-bold text-white",
        status === "ok" ? "bg-emerald-500" : "bg-[var(--destructive)]",
      )}
    >
      {status === "ok" ? "✓" : "!"}
    </span>
  );
}

/**
 * Collapsible card for a single tool call.
 *
 * Collapsed by default: the user only needs to know what the assistant looked
 * up. Expanding shows the full arguments and result — which is exactly what
 * answers "why did it conclude that?".
 */
export function ToolCallCard({ call }: { call: ToolCallView }) {
  const [open, setOpen] = useState(false);
  const hasArgs = Object.keys(call.args).length > 0;
  const hasDetails = hasArgs || Boolean(call.result || call.error);

  return (
    <div
      className={cn(
        "k8s-fade-in overflow-hidden rounded-lg border text-sm transition-colors",
        call.status === "error" && "border-[var(--destructive)]/40",
        call.status === "running" && "border-amber-500/40 bg-amber-500/5",
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={open}
      >
        <StatusIcon status={call.status} />

        <code className="font-medium">{call.name}</code>

        <span className="text-xs text-[var(--muted-foreground)]">
          {STATUS_LABEL[call.status]}
          {call.durationMs != null && ` · ${formatDuration(call.durationMs)}`}
        </span>

        {hasDetails && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            {open ? "collapse" : "details"}
          </span>
        )}
      </button>

      <div className="k8s-collapse" data-open={open && hasDetails}>
        <div>
          <div className="space-y-2 border-t px-3 py-2">
            <div>
              <p className="mb-1 text-xs text-[var(--muted-foreground)]">Arguments</p>
              <pre className="overflow-x-auto rounded bg-[var(--muted)] p-2 text-xs">
                {hasArgs ? JSON.stringify(call.args, null, 2) : "(none)"}
              </pre>
            </div>

            {(call.result || call.error) && (
              <div>
                <p className="mb-1 text-xs text-[var(--muted-foreground)]">
                  {call.error ? "Error" : "Result"}
                </p>
                <pre
                  className={cn(
                    "max-h-72 overflow-auto whitespace-pre-wrap rounded p-2 text-xs",
                    call.error
                      ? "bg-[var(--destructive)]/10 text-[var(--destructive)]"
                      : "bg-[var(--muted)]",
                  )}
                >
                  {call.error ?? call.result}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
