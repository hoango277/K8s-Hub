"use client";

import Link from "next/link";
import { ArrowRight, Stethoscope } from "lucide-react";

import { RunStatus, targetLabel } from "@/components/rca/shared";
import { useRcaRun } from "@/hooks/use-rca";

/**
 * Strip above a conversation opened from a diagnosis ("Ask in chat"): which run it
 * is about, and the way back to it. The assistant knows the same run — every turn
 * tells it (backend chat.py → CONVERSATION CONTEXT) and it reads the findings
 * with get_diagnosis.
 */
export function RcaContext({ runId }: { runId: string }) {
  const { data: run, isLoading, error } = useRcaRun(runId);
  return (
    <div className="border-b bg-[var(--card)] px-4 py-2">
      <div className="mx-auto flex min-h-8 max-w-3xl flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        <Stethoscope aria-hidden className="size-4 shrink-0 text-[var(--brand)]" />
        {isLoading ? (
          <span aria-label="Loading the diagnosis" className="h-4 w-56 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
        ) : error || !run ? (
          <span className="text-[var(--muted-foreground)]">
            The diagnosis this chat was opened from isn&apos;t available any more.
          </span>
        ) : (
          <>
            <span className="min-w-0 truncate">
              <span className="text-[var(--muted-foreground)]">About the diagnosis of </span>
              <span className="font-medium">{targetLabel(run)}</span>
            </span>
            <RunStatus run={run} />
            <Link
              href={`/rca/${run.id}`}
              className="ml-auto inline-flex h-8 items-center gap-1 rounded-full px-3 text-xs font-medium text-[var(--brand)] outline-none transition hover:bg-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] motion-reduce:transition-none"
            >
              Open diagnosis
              <ArrowRight aria-hidden className="size-3.5" />
            </Link>
          </>
        )}
      </div>
    </div>
  );
}
