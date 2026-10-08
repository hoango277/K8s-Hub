"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronRight, Plus, SearchCheck, Stethoscope } from "lucide-react";

import { CATEGORY, RunStatus, TRIGGER, targetLabel, when } from "@/components/rca/shared";
import { NewDiagnosisDialog } from "@/components/rca/new-diagnosis-dialog";
import { ErrorPanel } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useRcaRuns } from "@/hooks/use-rca";
import { cn } from "@/lib/utils";
import type { EventCategory, RcaRunSummary, RcaTrigger } from "@/types/rca";

const FILTERS: { id: RcaTrigger | null; label: string }[] = [
  { id: null, label: "All" },
  { id: "manual", label: "Started here" },
  { id: "chat", label: "From chat" },
  { id: "alert", label: "From alerts" },
  { id: "scan", label: "Periodic scan" },
];

// Event type → category, for the colour of the top cause. Only the common ones;
// anything else shows neutral.
const TYPE_CATEGORY: Record<string, EventCategory> = {
  Rollout: "change", ConfigChange: "change", ScaleChange: "change", ApprovalExecuted: "change",
  NodeCordon: "change", MemoryNearLimit: "resource", CpuThrottling: "resource",
  NodePressure: "resource", NodeSaturated: "resource", NodeNotReady: "resource",
  PvcPending: "resource", HpaAtMax: "resource",
};

export function RcaListPage() {
  const [filter, setFilter] = useState<RcaTrigger | null>(null);
  const [creating, setCreating] = useState(false);
  const { data, isLoading, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useRcaRuns(filter);
  const items = data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:px-6">
      <PageHeader
        icon={Stethoscope}
        title="Diagnosis"
        description="Find the root cause of a problem: events are detected, linked by causal rules and ranked, then checked by the AI."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus aria-hidden /> New diagnosis
          </Button>
        }
      />

      <div role="group" aria-label="Filter by origin" className="mb-6 flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const active = f.id === filter;
          return (
            <button
              key={f.label}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(f.id)}
              className={cn(
                "h-8 rounded-md border px-3 text-sm outline-none transition motion-reduce:transition-none",
                "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                active
                  ? "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
              )}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <ul aria-busy="true" aria-label="Loading diagnoses" className="space-y-3">
          {[0, 1, 2].map((i) => (
            <li key={i} className="k8s-skeleton h-[4.5rem] rounded-lg border" />
          ))}
        </ul>
      ) : error ? (
        <ErrorPanel title="Couldn't load diagnoses" error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={SearchCheck}
          title={filter ? `No diagnoses ${FILTERS.find((f) => f.id === filter)!.label.toLowerCase()}` : "No diagnoses yet"}
          description={
            filter === "chat"
              ? "Ask the assistant why something is broken; it runs a diagnosis and links it here."
              : filter === "alert"
                ? "When Alertmanager sends an alert to K8s-Hub, it is diagnosed automatically and shows up here."
                : filter === "scan"
                  ? "Turn on the periodic scan in Settings (Cluster access) to diagnose new problems without being asked."
                  : "Start one for a namespace or a workload. It takes a few seconds, plus up to a minute for the AI report."
          }
        >
          {filter !== "alert" && filter !== "scan" && (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden /> New diagnosis
            </Button>
          )}
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <ul className="space-y-3">
            {items.map((run) => (
              <li key={run.id}>
                <RunRow run={run} />
              </li>
            ))}
          </ul>
          {hasNextPage && (
            <div className="flex justify-center">
              <Button variant="outline" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
                {isFetchingNextPage && <Spinner />}
                Load more
              </Button>
            </div>
          )}
        </div>
      )}

      <NewDiagnosisDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function RunRow({ run }: { run: RcaRunSummary }) {
  const category = run.top_cause_type ? TYPE_CATEGORY[run.top_cause_type] ?? "symptom" : null;
  return (
    <Link
      href={`/rca/${run.id}`}
      className={cn(
        "group flex items-center gap-4 rounded-lg border bg-[var(--card)] p-4 outline-none transition motion-reduce:transition-none",
        "hover:bg-[var(--accent)]/50 focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{targetLabel(run)}</span>
          <RunStatus run={run} />
          {category && run.status === "completed" && (
            <Badge tone={CATEGORY[category].tone}>{run.top_cause_type}</Badge>
          )}
        </div>
        <p className="mt-1 line-clamp-2 text-sm text-[var(--muted-foreground)]">
          {run.status === "failed"
            ? run.error
            : run.top_cause ?? (run.status === "completed" ? "No cause found in the window." : "Looking for the cause…")}
        </p>
        <p className="mt-1 text-xs text-[var(--muted-foreground)]">
          {TRIGGER[run.trigger]} · {run.requested_by_email} · {when(run.created_at)}
        </p>
      </div>
      <ChevronRight
        aria-hidden
        className="size-4 shrink-0 text-[var(--muted-foreground)] transition group-hover:translate-x-0.5 motion-reduce:transition-none"
      />
    </Link>
  );
}
