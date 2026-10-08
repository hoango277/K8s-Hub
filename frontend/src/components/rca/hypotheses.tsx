"use client";

import { ArrowDown, Check, Crosshair, X } from "lucide-react";

import { CATEGORY, VERDICT, clock, entityLabel } from "@/components/rca/shared";
import { errorMessage } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useHypothesisFeedback } from "@/hooks/use-rca";
import type { RcaEdge, RcaEvent, RcaHypothesis, RcaReport } from "@/types/rca";

export function Hypotheses({
  hypotheses,
  events,
  edges,
  report,
  onShow,
  runId,
  canJudge,
}: {
  hypotheses: RcaHypothesis[];
  events: Map<string, RcaEvent>;
  edges: RcaEdge[];
  report: RcaReport | null;
  onShow: (eventId: string) => void;
  runId: string;
  /** Engineers and admins: their judgement trains the ranking (backend/app/modules/rca/learning.py). */
  canJudge: boolean;
}) {
  const reasons = new Map((report?.verdicts ?? []).map((v) => [v.rank, v.reason]));
  const chosen = report?.root_cause_rank ?? null;
  return (
    <ol className="space-y-3">
      {hypotheses.map((h) => {
        const root = events.get(h.event_id);
        if (!root) return null;
        const cat = CATEGORY[root.category];
        return (
          <li
            key={h.rank}
            className={
              "rounded-lg border bg-[var(--card)] p-4" + (chosen === h.rank ? " ring-2 ring-[var(--primary)]/60" : "")
            }
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold text-[var(--muted-foreground)]">#{h.rank}</span>
                  <h3 className="font-semibold">{root.title}</h3>
                  <Badge tone={cat.tone}>{cat.label}</Badge>
                  {h.verdict && <Badge tone={VERDICT[h.verdict].tone}>{VERDICT[h.verdict].label}</Badge>}
                  {chosen === h.rank && <Badge tone="success">AI&apos;s root cause</Badge>}
                </div>
                <p className="mt-1 text-sm">{root.summary}</p>
                <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  {entityLabel(root.entity)} · {clock(root.start)} · score {(h.score * 100).toFixed(0)}%
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => onShow(h.event_id)}>
                <Crosshair aria-hidden /> Show in graph
              </Button>
            </div>

            {reasons.get(h.rank) && (
              <p className="mt-3 rounded-md bg-[var(--muted)] px-3 py-2 text-sm">
                <span className="font-medium">AI check: </span>
                {reasons.get(h.rank)}
              </p>
            )}

            {h.chain.length > 1 && (
              <div className="mt-3">
                <p className="text-xs font-medium text-[var(--muted-foreground)]">How it leads to the symptom</p>
                <ol className="mt-1.5 space-y-1">
                  {h.chain.map((id, i) => {
                    const ev = events.get(id);
                    const edge = i > 0 ? edges.find((e) => e.cause === h.chain[i - 1] && e.effect === id) : null;
                    if (!ev) return null;
                    return (
                      <li key={id} className="text-sm">
                        {edge && (
                          <p className="flex items-center gap-1.5 py-0.5 pl-1 text-xs text-[var(--muted-foreground)]">
                            <ArrowDown aria-hidden className="size-3.5 shrink-0" />
                            <span>{edge.why}</span>
                          </p>
                        )}
                        <p>
                          <span className="font-medium">{ev.title}</span>{" "}
                          <span className="text-[var(--muted-foreground)]">
                            — {entityLabel(ev.entity)}, {clock(ev.start)}
                          </span>
                        </p>
                      </li>
                    );
                  })}
                </ol>
              </div>
            )}

            {(canJudge || h.feedback) && <Feedback runId={runId} hypothesis={h} canJudge={canJudge} />}

            {root.evidence.length > 0 && (
              <ul className="mt-3 space-y-1 border-t pt-3">
                {root.evidence.slice(0, 3).map((ev) => (
                  <li key={ev.id} className="break-words text-xs text-[var(--muted-foreground)]">
                    <span className="font-mono">[{ev.source}]</span> {ev.text}
                  </li>
                ))}
              </ul>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Feedback({
  runId,
  hypothesis,
  canJudge,
}: {
  runId: string;
  hypothesis: RcaHypothesis;
  canJudge: boolean;
}) {
  const judge = useHypothesisFeedback(runId);
  const toast = useToast();
  const current = hypothesis.feedback ?? null;
  const send = (correct: boolean) =>
    judge.mutate(
      { rank: hypothesis.rank, correct },
      {
        onSuccess: () =>
          toast({
            kind: "ok",
            message: correct
              ? "Thanks — causes like this will rank a little higher."
              : "Thanks — causes like this will rank a little lower.",
          }),
        onError: (e) => toast({ kind: "error", message: errorMessage(e, "Couldn't save your feedback.") }),
      },
    );

  if (!canJudge) {
    return (
      <p className="mt-3 text-xs text-[var(--muted-foreground)]">
        Marked {current === "correct" ? "the root cause" : "not the cause"}
        {hypothesis.feedback_by_email ? ` by ${hypothesis.feedback_by_email}` : ""}.
      </p>
    );
  }
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3">
      <span id={`fb-${hypothesis.rank}`} className="text-xs text-[var(--muted-foreground)]">
        Was this the root cause?
      </span>
      <div role="group" aria-labelledby={`fb-${hypothesis.rank}`} className="flex gap-1.5">
        <Button
          variant={current === "correct" ? "primary" : "outline"}
          size="sm"
          aria-pressed={current === "correct"}
          disabled={judge.isPending}
          onClick={() => send(true)}
        >
          {judge.isPending && judge.variables?.correct ? <Spinner /> : <Check aria-hidden />}
          Right cause
        </Button>
        <Button
          variant={current === "wrong" ? "primary" : "outline"}
          size="sm"
          aria-pressed={current === "wrong"}
          disabled={judge.isPending}
          onClick={() => send(false)}
        >
          {judge.isPending && judge.variables?.correct === false ? <Spinner /> : <X aria-hidden />}
          Not it
        </Button>
      </div>
      {current && hypothesis.feedback_by_email && (
        <span className="text-xs text-[var(--muted-foreground)]">by {hypothesis.feedback_by_email}</span>
      )}
    </div>
  );
}
