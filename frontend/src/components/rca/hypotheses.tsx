"use client";

import Link from "next/link";
import { ArrowDown, BookOpen, Check, ListChecks, MessagesSquare, X } from "lucide-react";

import { FixRow } from "@/components/rca/fix-row";
import { CATEGORY, Fold, Steps, VERDICT, clock, entityLabel } from "@/components/rca/shared";
import { errorMessage } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useAskInChat } from "@/hooks/use-ask-in-chat";
import { useHypothesisFeedback } from "@/hooks/use-rca";
import { cn } from "@/lib/utils";
import type { RcaEdge, RcaEvent, RcaFix, RcaHypothesis, RcaReport, RcaSkillRef } from "@/types/rca";

/**
 * Each fix belongs to the first cause whose chain head (root + 2 next events) holds
 * its event — the same walk remediation.candidates() makes, so a fix shows once.
 */
function fixesByRank(hypotheses: RcaHypothesis[], fixes: RcaFix[]): Map<number, RcaFix[]> {
  const out = new Map<number, RcaFix[]>();
  const taken = new Set<string>();
  for (const h of hypotheses) {
    const head = new Set((h.chain.length ? h.chain : [h.event_id]).slice(0, 3));
    const mine = fixes.filter((f) => !taken.has(f.id) && head.has(f.event_id));
    mine.forEach((f) => taken.add(f.id));
    out.set(h.rank, mine);
  }
  return out;
}

export function Hypotheses({
  hypotheses,
  events,
  edges,
  report,
  focused,
  onFocus,
  runId,
  canJudge,
}: {
  hypotheses: RcaHypothesis[];
  events: Map<string, RcaEvent>;
  edges: RcaEdge[];
  report: RcaReport | null;
  /** Rank whose chain is highlighted in the graph. */
  focused: number | null;
  onFocus: (rank: number) => void;
  runId: string;
  /** Engineers and admins: their judgement trains the ranking (backend/app/modules/rca/learning.py). */
  canJudge: boolean;
}) {
  const verdicts = new Map((report?.verdicts ?? []).map((v) => [v.rank, v]));
  const chosen = report?.root_cause_rank ?? null;
  const fixes = fixesByRank(hypotheses, report?.fix_candidates ?? []);
  return (
    <ol className="space-y-3">
      {hypotheses.map((h) => {
        const root = events.get(h.event_id);
        if (!root) return null;
        const verdict = verdicts.get(h.rank);
        const mine = fixes.get(h.rank) ?? [];
        const advice = mine.filter((f) => !f.proposable);
        const steps = [...(verdict?.next_steps ?? []), ...advice.map((f) => f.title)];
        const isFocused = focused === h.rank;
        const isRoot = chosen === h.rank;
        const cat = CATEGORY[root.category];
        const CatIcon = cat.icon;
        return (
          <li
            key={h.rank}
            className={cn(
              // Plain card; the category shows on the icon. Only the AI's root cause gets a
              // stripe — three red "symptom" stripes in a row read as an alarm, not a ranking.
              "rounded-lg border bg-[var(--card)] transition-[box-shadow,opacity] motion-reduce:transition-none",
              isRoot && "border-[var(--success)]/40 border-l-4 border-l-[var(--success)] bg-[var(--success)]/5",
              h.verdict === "refuted" && !isFocused && "opacity-70",
              isFocused && "ring-2 ring-[var(--brand)]/60",
            )}
          >
            <button
              type="button"
              aria-pressed={isFocused}
              aria-label={`#${h.rank} ${root.title} on ${entityLabel(root.entity)}. Show its path in the graph`}
              onClick={() => onFocus(h.rank)}
              className="block w-full rounded-t-lg px-4 pb-2 pt-3 text-left outline-none hover:bg-[var(--accent)]/50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ring)]"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span
                  aria-hidden
                  className={cn(
                    "flex size-6 items-center justify-center rounded-full text-xs font-bold",
                    isRoot
                      ? "bg-[var(--success)] text-[var(--success-foreground)]"
                      : "bg-[var(--muted)] text-[var(--foreground)] ring-1 ring-inset ring-[var(--border)]",
                  )}
                >
                  {h.rank}
                </span>
                <CatIcon aria-hidden className={cn("size-4", cat.text)} />
                <span className="font-semibold">{root.title}</span>
                {isRoot && (
                  <Badge tone="success" className="gap-1">
                    <Check aria-hidden className="size-3" /> Root cause
                  </Badge>
                )}
                {h.verdict && !isRoot && <Badge tone={VERDICT[h.verdict].tone}>{VERDICT[h.verdict].label}</Badge>}
              </span>
              {/* The object's name tells causes apart: three "Container restarted" in a row is common. */}
              <span className="mt-0.5 flex min-w-0 items-baseline gap-1.5 text-sm">
                <span className="truncate font-mono font-medium">{root.entity.name}</span>
                <span className="shrink-0 text-xs text-[var(--muted-foreground)]">
                  {root.entity.sub || root.entity.kind}
                  {root.entity.namespace ? ` in ${root.entity.namespace}` : ""} · {clock(root.start)}
                </span>
              </span>
            </button>

            <div className="space-y-2 px-4 pb-3">
              {(steps.length > 0 || mine.some((f) => f.proposable)) && (
                <div>
                  {steps.length > 0 && (
                    <>
                      <p className="eyebrow flex items-center gap-1.5 text-[var(--muted-foreground)]">
                        <ListChecks aria-hidden className="size-4" /> Next steps
                      </p>
                      <Steps steps={steps} label={`Next steps for #${h.rank}`} />
                    </>
                  )}
                  {mine
                    .filter((f) => f.proposable)
                    .map((f) => (
                      <div key={f.id} className="mt-2">
                        <FixRow runId={runId} fix={f} aiPick={report?.fix?.id === f.id} />
                      </div>
                    ))}
                </div>
              )}

              {(h.skills?.length ?? 0) > 0 && (
                <SuggestedSkills
                  runId={runId}
                  rank={h.rank}
                  cause={`${root.title} on ${entityLabel(root.entity)}`}
                  skills={h.skills!}
                />
              )}

              <Fold summary="Why and evidence">
                <Why hypothesis={h} root={root} reason={verdict?.reason} events={events} edges={edges} />
              </Fold>

              {(canJudge || h.feedback) && <Feedback runId={runId} hypothesis={h} canJudge={canJudge} />}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

/**
 * Runbooks for this cause: skills whose SKILL.md lists one of the chain's event types
 * (metadata.rca-events). "Investigate in chat" opens the diagnosis' conversation with
 * the request prepared in the composer — the user reads it and sends it.
 */
function SuggestedSkills({
  runId,
  rank,
  cause,
  skills,
}: {
  runId: string;
  rank: number;
  cause: string;
  skills: RcaSkillRef[];
}) {
  const { ask, busy } = useAskInChat();
  return (
    <div>
      <p className="eyebrow flex items-center gap-1.5 text-[var(--muted-foreground)]">
        <BookOpen aria-hidden className="size-4" /> Suggested skill
      </p>
      <ul className="mt-1 space-y-1">
        {skills.map((s) => (
          <li key={s.name} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <Link
              href={`/skills/${s.name}`}
              className="rounded-sm font-mono text-sm font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              {s.name}
            </Link>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() =>
                void ask(runId, `Use the ${s.name} skill to investigate cause #${rank} (${cause}).`)
              }
            >
              {busy ? <Spinner /> : <MessagesSquare aria-hidden />}
              Investigate in chat
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Why({
  hypothesis: h,
  root,
  reason,
  events,
  edges,
}: {
  hypothesis: RcaHypothesis;
  root: RcaEvent;
  reason?: string;
  events: Map<string, RcaEvent>;
  edges: RcaEdge[];
}) {
  const cat = CATEGORY[root.category];
  return (
    <div className="space-y-3 pb-1 text-sm">
      <p>
        <Badge tone={cat.tone} className="mr-2 align-middle">
          {cat.label}
        </Badge>
        {root.summary}
        <span className="text-[var(--muted-foreground)]"> · score {(h.score * 100).toFixed(0)}%</span>
      </p>
      {reason && (
        <p className="rounded-md bg-[var(--muted)] px-3 py-2">
          <span className="font-medium">AI: </span>
          {reason}
        </p>
      )}
      {h.chain.length > 1 && (
        <ol aria-label="How it leads to the symptom" className="space-y-1">
          {h.chain.map((id, i) => {
            const ev = events.get(id);
            const edge = i > 0 ? edges.find((e) => e.cause === h.chain[i - 1] && e.effect === id) : null;
            if (!ev) return null;
            return (
              <li key={id}>
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
      )}
      {root.evidence.length > 0 && (
        <ul aria-label="Evidence" className="space-y-1">
          {root.evidence.map((ev) => (
            <li
              key={ev.id}
              className="break-words rounded-md bg-[var(--muted)] px-3 py-1.5 font-mono text-xs text-[var(--muted-foreground)]"
            >
              [{ev.source}] {ev.text}
            </li>
          ))}
        </ul>
      )}
    </div>
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
      <p className="text-xs text-[var(--muted-foreground)]">
        Marked {current === "correct" ? "the root cause" : "not the cause"}
        {hypothesis.feedback_by_email ? ` by ${hypothesis.feedback_by_email}` : ""}.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2 border-t pt-2">
      <span id={`fb-${hypothesis.rank}`} className="text-xs text-[var(--muted-foreground)]">
        Root cause?
      </span>
      <div role="group" aria-labelledby={`fb-${hypothesis.rank}`} className="flex gap-1.5">
        <Button
          variant={current === "correct" ? "primary" : "ghost"}
          size="sm"
          aria-pressed={current === "correct"}
          disabled={judge.isPending}
          onClick={() => send(true)}
        >
          {judge.isPending && judge.variables?.correct ? <Spinner /> : <Check aria-hidden />}
          Yes
        </Button>
        <Button
          variant={current === "wrong" ? "primary" : "ghost"}
          size="sm"
          aria-pressed={current === "wrong"}
          disabled={judge.isPending}
          onClick={() => send(false)}
        >
          {judge.isPending && judge.variables?.correct === false ? <Spinner /> : <X aria-hidden />}
          No
        </Button>
      </div>
      {current && hypothesis.feedback_by_email && (
        <span className="text-xs text-[var(--muted-foreground)]">by {hypothesis.feedback_by_email}</span>
      )}
    </div>
  );
}
