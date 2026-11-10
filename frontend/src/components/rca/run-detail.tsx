"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { MessagesSquare, Network, Repeat, SearchX, Stethoscope, TriangleAlert } from "lucide-react";

import { CausalGraph, GraphLegend } from "@/components/rca/causal-graph";
import { EventDetails } from "@/components/rca/event-details";
import { Dependencies } from "@/components/rca/dependencies";
import { Hypotheses } from "@/components/rca/hypotheses";
import { ReportPanel } from "@/components/rca/report-panel";
import { Fold, PendingIcon, RunStatus, StepIcon, TRIGGER, targetLabel, windowLabel } from "@/components/rca/shared";
import { Timeline } from "@/components/rca/timeline";
import { ErrorPanel, LoadingRow, errorMessage } from "@/components/skills/shared";
import { BackLink } from "@/components/ui/back-link";
import { Button, buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useAskInChat } from "@/hooks/use-ask-in-chat";
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
            <Link href="/rca" className={buttonVariants({ variant: "outline", size: "sm" })}>
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
    <div className="mx-auto max-w-7xl px-4 pb-16 pt-6 sm:px-6">
      <BackLink href="/rca">All diagnoses</BackLink>
      {children}
    </div>
  );
}

/** On narrow screens the graph sits below the causes; bring it up when a cause is picked. */
function revealGraph() {
  const el = document.getElementById("rca-graph");
  if (!el || window.matchMedia("(min-width: 1024px)").matches) return; // side by side: already visible
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  el.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
}

function Loaded({ run }: { run: RcaRun }) {
  // Node whose details are open, and the cause whose path is highlighted. Separate:
  // opening an event's details shouldn't lose the chain being followed.
  const [selected, setSelected] = useState<string | null>(null);
  const [focusRank, setFocusRank] = useState<number | null>(null);
  const { data: me } = useCurrentUser();
  const canJudge = me ? hasRole(me.role, ["engineer"]) : false;
  const graph = run.graph;
  const hyps = run.hypotheses;
  const events = useMemo(() => new Map((graph?.events ?? []).map((e) => [e.id, e])), [graph]);
  const inGraph = useMemo(() => (graph?.events ?? []).filter((e) => e.in_graph), [graph]);
  const ranks = useMemo(() => new Map(hyps.map((h) => [h.event_id, h.rank])), [hyps]);
  const analysing = run.status === "pending" || run.status === "running";
  const selectedEvent = selected ? events.get(selected) : undefined;
  // Until someone picks a cause, follow the AI's pick, else the top-ranked one.
  const rank = focusRank ?? run.report?.root_cause_rank ?? hyps[0]?.rank ?? null;
  const focused = hyps.find((h) => h.rank === rank);
  const path = useMemo(() => (focused ? (focused.chain.length ? focused.chain : [focused.event_id]) : []), [focused]);
  // A real cluster's graph has dozens of events and crossing links; by default draw only
  // the focused cause's path, which is what a reader follows anyway.
  const [showAll, setShowAll] = useState(false);
  const shown = useMemo(() => {
    if (showAll || path.length === 0) return inGraph;
    const keep = new Set([...path, ...(selected ? [selected] : [])]);
    return inGraph.filter((e) => keep.has(e.id));
  }, [showAll, path, selected, inGraph]);

  function focusCause(r: number) {
    setFocusRank(r);
    setSelected(null);
    revealGraph();
  }

  function selectEvent(id: string) {
    setSelected(id);
    // Follow the chain this event belongs to, unless it's on the one already shown.
    if (!path.includes(id)) {
      const owner = hyps.find((h) => h.chain.includes(id) || h.event_id === id);
      if (owner) setFocusRank(owner.rank);
    }
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
        actions={
          !isActive(run) && (
            <>
              <AskInChat runId={run.id} />
              <RunAgain run={run} />
            </>
          )
        }
      />

      {(analysing || run.status === "failed") && <Progress run={run} />}

      {run.status === "failed" && (
        <div role="alert" className="mt-4 rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4 text-sm">
          <p className="font-medium text-[var(--destructive)]">The diagnosis failed</p>
          <p className="mt-1 text-[var(--muted-foreground)]">{run.error ?? "Unknown error."} Run it again to retry.</p>
        </div>
      )}

      {run.status === "completed" && (
        <div className="space-y-6">
          <ReportPanel run={run} />

          {run.warnings.length > 0 && (
            <div className="rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/5 px-3 py-1">
              <Fold
                summary={
                  <span className="flex items-center gap-2 text-[var(--warning)]">
                    <TriangleAlert aria-hidden className="size-4" />
                    {run.warnings.length} gap{run.warnings.length === 1 ? "" : "s"} in what could be checked
                  </span>
                }
              >
                <ul className="list-disc space-y-0.5 pb-2 pl-4 text-sm text-[var(--muted-foreground)]">
                  {run.warnings.map((w) => (
                    <li key={w} className="break-words">
                      {w}
                    </li>
                  ))}
                </ul>
              </Fold>
            </div>
          )}

          {hyps.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No cause found"
              description="Nothing anomalous was detected in this window. Try a longer look-back, or check that metrics, logs and events are collected."
            />
          ) : (
            <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
              <section aria-labelledby="rca-causes">
                <h2 id="rca-causes" className="mb-1 text-lg font-semibold">
                  Likely root causes
                </h2>
                <p className="mb-3 text-xs text-[var(--muted-foreground)]">
                  Ranked by causal rules. Select one to trace it in the graph. Fixes go to approval first.
                </p>
                <Hypotheses
                  hypotheses={hyps}
                  events={events}
                  edges={graph?.edges ?? []}
                  report={run.report}
                  focused={rank}
                  onFocus={focusCause}
                  runId={run.id}
                  canJudge={canJudge}
                />
              </section>

              {inGraph.length > 0 && (
                <section
                  aria-labelledby="rca-graph-title"
                  id="rca-graph"
                  className="scroll-mt-4 lg:sticky lg:top-4 lg:max-h-[calc(100vh-2rem)] lg:overflow-y-auto"
                >
                  <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
                    <h2 id="rca-graph-title" className="flex items-center gap-2 text-lg font-semibold">
                      <Network aria-hidden className="size-5" /> Causal graph
                    </h2>
                    {path.length > 0 && path.length < inGraph.length && (
                      <div role="group" aria-label="Graph view" className="flex rounded-md border p-0.5">
                        <Button
                          size="sm"
                          variant={showAll ? "ghost" : "primary"}
                          aria-pressed={!showAll}
                          onClick={() => setShowAll(false)}
                        >
                          Path of #{focused?.rank}
                        </Button>
                        <Button
                          size="sm"
                          variant={showAll ? "primary" : "ghost"}
                          aria-pressed={showAll}
                          onClick={() => setShowAll(true)}
                        >
                          All {inGraph.length} events
                        </Button>
                      </div>
                    )}
                  </div>
                  <p className="mb-3 text-xs text-[var(--muted-foreground)]">
                    Causes on top, symptoms below. Select an event for its evidence.
                  </p>
                  <CausalGraph
                    events={shown}
                    edges={graph?.edges ?? []}
                    ranks={ranks}
                    path={path}
                    selected={selected}
                    onSelect={selectEvent}
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
                        onSelect={selectEvent}
                        onClose={() => setSelected(null)}
                      />
                    </div>
                  )}
                </section>
              )}
            </div>
          )}

          <div className="space-y-1 border-t pt-3">
            {(graph?.events.length ?? 0) > 0 && (
              <Fold summary={`Timeline (${graph!.events.length} events)`}>
                <div className="pb-3">
                  <Timeline
                    events={graph!.events}
                    selected={selected}
                    onSelect={(id) => {
                      selectEvent(id);
                      document.getElementById("rca-graph")?.scrollIntoView({ block: "start" });
                    }}
                  />
                </div>
              </Fold>
            )}
            {graph?.namespaces && (
              <Fold summary="What was analysed (namespaces and who calls whom)">
                <div className="pb-3">
                  <Dependencies namespaces={graph.namespaces} dependencies={graph.dependencies ?? []} />
                </div>
              </Fold>
            )}
          </div>
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

/** Continue in the chat with this run as context (the assistant reads it with get_diagnosis). */
function AskInChat({ runId }: { runId: string }) {
  const { ask, busy } = useAskInChat();
  return (
    <Button variant="outline" disabled={busy} onClick={() => void ask(runId)}>
      {busy ? <Spinner /> : <MessagesSquare aria-hidden />}
      Ask in chat
    </Button>
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
