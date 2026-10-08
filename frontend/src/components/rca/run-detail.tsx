"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Network, Repeat, SearchX, Stethoscope, TriangleAlert } from "lucide-react";

import { CausalGraph, GraphLegend } from "@/components/rca/causal-graph";
import { EventDetails } from "@/components/rca/event-details";
import { Dependencies } from "@/components/rca/dependencies";
import { Hypotheses } from "@/components/rca/hypotheses";
import { ReportPanel } from "@/components/rca/report-panel";
import { PendingIcon, RunStatus, StepIcon, TRIGGER, targetLabel, windowLabel } from "@/components/rca/shared";
import { Timeline } from "@/components/rca/timeline";
import { ErrorPanel, LoadingRow, errorMessage } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { isActive, useRcaRun, useStartRca } from "@/hooks/use-rca";
import { useCurrentUser } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import type { RcaRun } from "@/types/rca";

// Shown greyed out until the backend reports them, so progress reads as a checklist.
const STEPS = [
  { key: "snapshot", label: "Read the cluster" },
  { key: "events", label: "Collect Kubernetes events" },
  { key: "detect_state", label: "Check pods, workloads, nodes and changes" },
  { key: "detect_telemetry", label: "Look for anomalies in metrics, logs and traces" },
  { key: "graph", label: "Link events with causal rules" },
  { key: "rank", label: "Rank root-cause candidates" },
];

export function RunDetail({ id }: { id: string }) {
  const { data: run, isLoading, error, refetch } = useRcaRun(id);

  if (isLoading) {
    return (
      <Shell>
        <LoadingRow label="Loading the diagnosis…" />
      </Shell>
    );
  }
  if (error) {
    const missing = error instanceof ApiError && error.status === 404;
    return (
      <Shell>
        {missing ? (
          <EmptyState
            icon={SearchX}
            title="Diagnosis not found"
            description="It may belong to someone else, or the link is wrong."
          >
            <Link
              href="/rca"
              className="inline-flex h-8 items-center gap-2 rounded-md border px-3 text-sm outline-none transition hover:bg-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              All diagnoses
            </Link>
          </EmptyState>
        ) : (
          <ErrorPanel title="Couldn't load the diagnosis" error={error} onRetry={() => void refetch()} />
        )}
      </Shell>
    );
  }
  return <Loaded run={run!} />;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-5xl px-4 pb-16 pt-6 sm:px-6">
      <Link
        href="/rca"
        className="mb-4 inline-flex items-center gap-1.5 rounded-sm text-sm text-[var(--muted-foreground)] outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        <ArrowLeft aria-hidden className="size-4" /> All diagnoses
      </Link>
      {children}
    </div>
  );
}

function Loaded({ run }: { run: RcaRun }) {
  const [selected, setSelected] = useState<string | null>(null);
  const { data: me } = useCurrentUser();
  const canJudge = me ? hasRole(me.role, ["engineer"]) : false;
  const graph = run.graph;
  const events = useMemo(() => new Map((graph?.events ?? []).map((e) => [e.id, e])), [graph]);
  const inGraph = useMemo(() => (graph?.events ?? []).filter((e) => e.in_graph), [graph]);
  const ranks = useMemo(() => new Map(run.hypotheses.map((h) => [h.event_id, h.rank])), [run.hypotheses]);
  const analysing = run.status === "pending" || run.status === "running";
  const selectedEvent = selected ? events.get(selected) : undefined;

  function show(id: string) {
    setSelected(id);
    document.getElementById("rca-graph")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  return (
    <Shell>
      <PageHeader
        icon={Stethoscope}
        title={`Diagnosis of ${targetLabel(run)}`}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <RunStatus run={run} />
            <span>
              {windowLabel(run.window_start, run.window_end)} · {TRIGGER[run.trigger]} by {run.requested_by_email}
            </span>
          </span>
        }
        actions={!isActive(run) && <RunAgain run={run} />}
      />

      {(analysing || run.status === "failed") && <Progress run={run} />}

      {run.status === "failed" && (
        <div role="alert" className="mt-4 rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4 text-sm">
          <p className="font-medium text-[var(--destructive)]">The diagnosis failed</p>
          <p className="mt-1 text-[var(--muted-foreground)]">{run.error ?? "Unknown error."} Run it again to retry.</p>
        </div>
      )}

      {run.status === "completed" && (
        <div className="space-y-8">
          {run.warnings.length > 0 && (
            <div className="flex gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-3 text-sm">
              <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <div>
                <p className="font-medium">Gaps in what could be checked</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[var(--muted-foreground)]">
                  {run.warnings.map((w) => (
                    <li key={w} className="break-words">
                      {w}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <section aria-labelledby="rca-report">
            <h2 id="rca-report" className="mb-3 text-lg font-semibold">
              AI report
            </h2>
            <ReportPanel run={run} />
          </section>

          <section aria-labelledby="rca-causes">
            <h2 id="rca-causes" className="mb-1 text-lg font-semibold">
              Likely root causes
            </h2>
            <p className="mb-3 text-sm text-[var(--muted-foreground)]">
              Ranked by causal rules and timing, not by the AI. A cause is only linked to a symptom when a rule allows it.
            </p>
            {run.hypotheses.length === 0 ? (
              <EmptyState
                icon={SearchX}
                title="No cause found"
                description="Nothing anomalous was detected in this window. Try a longer look-back, or check that metrics, logs and events are collected."
              />
            ) : (
              <Hypotheses
                hypotheses={run.hypotheses}
                events={events}
                edges={graph?.edges ?? []}
                report={run.report}
                onShow={show}
                runId={run.id}
                canJudge={canJudge}
              />
            )}
          </section>

          {inGraph.length > 0 && (
            <section aria-labelledby="rca-graph-title" id="rca-graph" className="scroll-mt-4">
              <h2 id="rca-graph-title" className="mb-1 flex items-center gap-2 text-lg font-semibold">
                <Network aria-hidden className="size-5" /> Causal graph
              </h2>
              <p className="mb-3 text-sm text-[var(--muted-foreground)]">
                Causes on the left, symptoms on the right. Select an event to see its evidence.
              </p>
              <CausalGraph
                events={inGraph}
                edges={graph?.edges ?? []}
                ranks={ranks}
                selected={selected}
                onSelect={setSelected}
              />
              <div className="mt-2">
                <GraphLegend />
              </div>
              {selectedEvent && (
                <div className="mt-4">
                  <EventDetails
                    event={selectedEvent}
                    events={events}
                    edges={graph?.edges ?? []}
                    onSelect={setSelected}
                    onClose={() => setSelected(null)}
                  />
                </div>
              )}
            </section>
          )}

          {graph?.namespaces && (
            <section aria-labelledby="rca-scope">
              <h2 id="rca-scope" className="mb-1 text-lg font-semibold">
                What was analysed
              </h2>
              <p className="mb-3 text-sm text-[var(--muted-foreground)]">
                Who calls whom, from configuration, metrics, traces and logs. A cause in a dependency can explain a
                symptom here.
              </p>
              <Dependencies namespaces={graph.namespaces} dependencies={graph.dependencies ?? []} />
            </section>
          )}

          {(graph?.events.length ?? 0) > 0 && (
            <section aria-labelledby="rca-timeline">
              <h2 id="rca-timeline" className="mb-3 text-lg font-semibold">
                Timeline
              </h2>
              <Timeline events={graph!.events} selected={selected} onSelect={show} />
            </section>
          )}
        </div>
      )}
    </Shell>
  );
}

function Progress({ run }: { run: RcaRun }) {
  const reported = new Map(run.steps.map((s) => [s.key, s]));
  return (
    <ol aria-label="Progress" aria-live="polite" className="space-y-2 rounded-lg border bg-[var(--card)] p-4">
      {STEPS.map((step) => {
        const s = reported.get(step.key);
        const failedHere = run.status === "failed" && s?.status === "running";
        return (
          <li key={step.key} className="flex items-center gap-3 text-sm">
            {s ? <StepIcon status={failedHere ? "error" : s.status} /> : <PendingIcon />}
            <span className={s ? "" : "text-[var(--muted-foreground)]"}>{s?.label ?? step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

function RunAgain({ run }: { run: RcaRun }) {
  const start = useStartRca();
  const router = useRouter();
  const toast = useToast();
  const minutes = Math.round((new Date(run.window_end).getTime() - new Date(run.window_start).getTime()) / 60_000);
  return (
    <Button
      variant="outline"
      disabled={start.isPending}
      onClick={() =>
        start.mutate(
          {
            namespace: run.namespace,
            target_kind: run.target_kind,
            target_name: run.target_name,
            lookback_minutes: Math.min(1440, Math.max(15, minutes)),
            with_report: true,
          },
          {
            onSuccess: (next) => router.push(`/rca/${next.id}`),
            onError: (e) => toast({ kind: "error", message: errorMessage(e, "Couldn't start the diagnosis.") }),
          },
        )
      }
    >
      {start.isPending ? <Spinner /> : <Repeat aria-hidden />}
      Run again now
    </Button>
  );
}
