"use client";

import { format, formatDistanceToNow } from "date-fns";
import { ChevronRight, History, MessageSquare, MousePointerClick } from "lucide-react";

import { ErrorPanel, LoadingRow, OutputBlock, formatDuration, quoteArg } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { useSkillRuns } from "@/hooks/use-skills";
import { useToolRuns } from "@/hooks/use-tools";
import type { SkillRun } from "@/types/skill";
import type { ToolRun } from "@/types/tool";

// ---------------------------------------------------------------------------
// One run, collapsed to a summary line. <details> gives keyboard support and
// the expanded/collapsed announcement for free.
// ---------------------------------------------------------------------------

function RunShell({
  ok,
  title,
  meta,
  createdAt,
  durationMs,
  actor,
  children,
}: {
  ok: boolean;
  title: React.ReactNode;
  meta?: React.ReactNode;
  createdAt: string;
  durationMs: number;
  actor: string;
  children: React.ReactNode;
}) {
  return (
    <li>
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3 outline-none hover:bg-[var(--accent)]/50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--ring)] [&::-webkit-details-marker]:hidden">
          <ChevronRight
            aria-hidden
            className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)] transition-transform group-open:rotate-90 motion-reduce:transition-none"
          />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              {ok ? <Badge tone="success">Succeeded</Badge> : <Badge tone="danger">Failed</Badge>}
              <span className="min-w-0 break-all text-sm">{title}</span>
              {meta}
            </div>
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              <span className="break-all">{actor}</span>
              <span aria-hidden className="mx-1.5">
                ·
              </span>
              <time dateTime={createdAt} title={format(new Date(createdAt), "PPpp")}>
                {formatDistanceToNow(new Date(createdAt), { addSuffix: true })}
              </time>
              <span aria-hidden className="mx-1.5">
                ·
              </span>
              {formatDuration(durationMs)}
            </p>
          </div>
        </summary>
        <div className="space-y-2 px-4 pb-4 pl-11">{children}</div>
      </details>
    </li>
  );
}

export function SkillRunItem({ run, showSkill = true }: { run: SkillRun; showSkill?: boolean }) {
  const TriggerIcon = run.trigger === "chat" ? MessageSquare : MousePointerClick;
  return (
    <RunShell
      ok={run.ok}
      createdAt={run.created_at}
      durationMs={run.duration_ms}
      actor={run.actor_email}
      title={
        <>
          {showSkill && <span className="font-medium">{run.skill}</span>}
          {showSkill && <span className="text-[var(--muted-foreground)]"> / </span>}
          <code className="text-xs">{run.script}</code>
        </>
      }
      meta={
        <Badge tone="neutral">
          <TriggerIcon aria-hidden className="size-3" />
          {run.trigger === "chat" ? "From chat" : "Manual"}
        </Badge>
      }
    >
      <p className="text-xs text-[var(--muted-foreground)]">
        Exit code: <code>{run.exit_code ?? "none (didn't finish)"}</code>
      </p>
      {run.args.length > 0 && (
        <p className="break-all text-xs text-[var(--muted-foreground)]">
          Arguments: <code>{run.args.map(quoteArg).join(" ")}</code>
        </p>
      )}
      <OutputBlock text={run.output} />
    </RunShell>
  );
}

export function ToolRunItem({ run }: { run: ToolRun }) {
  const args = Object.keys(run.args).length > 0 ? JSON.stringify(run.args, null, 2) : null;
  return (
    <RunShell
      ok={run.ok}
      createdAt={run.created_at}
      durationMs={run.duration_ms}
      actor={run.actor_email}
      title={<code className="text-xs">{run.tool}</code>}
    >
      {args && (
        <div>
          <p className="mb-1 text-xs text-[var(--muted-foreground)]">Arguments</p>
          <OutputBlock text={args} className="max-h-40" />
        </div>
      )}
      <p className="text-xs text-[var(--muted-foreground)]">Output</p>
      <OutputBlock text={run.output} />
    </RunShell>
  );
}

// ---------------------------------------------------------------------------
// Paginated lists with all four states.
// ---------------------------------------------------------------------------

function MoreButton({ onClick, loading }: { onClick: () => void; loading: boolean }) {
  return (
    <div className="flex justify-center">
      <Button variant="outline" size="sm" onClick={onClick} disabled={loading}>
        {loading && <Spinner label="Loading more" />}
        {loading ? "Loading…" : "Show more"}
      </Button>
    </div>
  );
}

/** Script runs, for every skill or just one (`skill`). */
export function SkillRunList({ skill, emptyHint }: { skill: string | null; emptyHint: string }) {
  const q = useSkillRuns(skill);
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const total = q.data?.pages[0]?.total ?? 0;

  if (q.isLoading) return <LoadingRow label="Loading runs…" />;
  if (q.error) return <ErrorPanel title="Couldn't load script runs" error={q.error} onRetry={() => void q.refetch()} />;
  if (items.length === 0)
    return <EmptyState icon={History} title="No script runs yet" description={emptyHint} className="py-10" />;

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--muted-foreground)]">
        Showing {items.length} of {total}
      </p>
      <ol className="divide-y rounded-lg border">
        {items.map((r) => (
          <SkillRunItem key={r.id} run={r} showSkill={skill === null} />
        ))}
      </ol>
      {q.hasNextPage && <MoreButton onClick={() => void q.fetchNextPage()} loading={q.isFetchingNextPage} />}
    </div>
  );
}

export function ToolRunList() {
  const q = useToolRuns();
  const items = q.data?.pages.flatMap((p) => p.items) ?? [];
  const total = q.data?.pages[0]?.total ?? 0;

  if (q.isLoading) return <LoadingRow label="Loading runs…" />;
  if (q.error) return <ErrorPanel title="Couldn't load tool runs" error={q.error} onRetry={() => void q.refetch()} />;
  if (items.length === 0)
    return (
      <EmptyState
        icon={History}
        title="No tool runs yet"
        description="Use “Try it” on a tool under Tools to run it by hand; each run is recorded here with its arguments and output."
        className="py-10"
      >
        <a href="#tools" className="text-sm font-medium underline underline-offset-2 hover:opacity-80">
          Go to Tools
        </a>
      </EmptyState>
    );

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--muted-foreground)]">
        Showing {items.length} of {total}
      </p>
      <ol className="divide-y rounded-lg border">
        {items.map((r) => (
          <ToolRunItem key={r.id} run={r} />
        ))}
      </ol>
      {q.hasNextPage && <MoreButton onClick={() => void q.fetchNextPage()} loading={q.isFetchingNextPage} />}
    </div>
  );
}
