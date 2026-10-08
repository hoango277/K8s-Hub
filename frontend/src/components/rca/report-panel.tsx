"use client";

import { Bot, ListChecks, RefreshCw, ShieldAlert, Wrench } from "lucide-react";

import { ApprovalCard } from "@/components/chat/approval-card";
import { errorMessage, FormError } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useProposeFix, useRewriteReport } from "@/hooks/use-rca";
import type { RcaFix, RcaRun } from "@/types/rca";

export function ReportPanel({ run }: { run: RcaRun }) {
  const rewrite = useRewriteReport(run.id);
  const toast = useToast();
  const report = run.report;
  const write = () =>
    rewrite.mutate(
      {},
      { onError: (e) => toast({ kind: "error", message: errorMessage(e, "Couldn't start the report.") }) },
    );

  if (run.report_status === "running") {
    return (
      <Box>
        <div className="flex items-center gap-3 text-sm">
          <Spinner />
          <span>
            The AI is checking the top causes with read-only lookups and writing the report. This can take up to a
            minute.
          </span>
        </div>
      </Box>
    );
  }

  if (run.report_status === "none" || run.report_status === "failed" || !report) {
    return (
      <Box>
        <p className="text-sm">
          {run.report_status === "failed"
            ? "The AI report could not be written. The ranked causes below are still valid."
            : "No AI report for this diagnosis. The ranked causes below come from causal rules alone."}
        </p>
        {report?.error && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{report.error}</p>}
        <Button className="mt-3" variant="outline" size="sm" onClick={write} disabled={rewrite.isPending}>
          {rewrite.isPending ? <Spinner /> : <Bot aria-hidden />}
          {run.report_status === "failed" ? "Try again" : "Write AI report"}
        </Button>
      </Box>
    );
  }

  const candidates = report.fix_candidates ?? [];
  const chosen = report.fix ?? null;
  const advice = candidates.filter((f) => !f.proposable && f.id !== chosen?.id);

  return (
    <Box>
      <p className="text-base font-medium leading-relaxed">{report.summary}</p>
      {report.explanation && (
        <p className="mt-2 text-sm leading-relaxed text-[var(--muted-foreground)]">{report.explanation}</p>
      )}

      {(chosen || run.approval_id) && (
        <div className="mt-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Wrench aria-hidden className="size-4" /> Suggested fix
          </h3>
          {run.approval_id ? (
            <div className="mt-2">
              <ApprovalCard approvalId={run.approval_id} />
            </div>
          ) : (
            chosen && <FixRow runId={run.id} fix={chosen} />
          )}
        </div>
      )}

      {(report.next_steps?.length ?? 0) > 0 && (
        <div className="mt-4">
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <ListChecks aria-hidden className="size-4" /> Next steps
          </h3>
          <ul className="mt-1.5 list-disc space-y-1 pl-5 text-sm">
            {report.next_steps!.map((s) => (
              <li key={s}>{s}</li>
            ))}
            {advice.map((f) => (
              <li key={f.id}>{f.title}</li>
            ))}
          </ul>
        </div>
      )}

      {(report.tool_evidence?.length ?? 0) > 0 && (
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer rounded-sm font-medium outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]">
            What the AI looked up ({report.tool_evidence!.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {report.tool_evidence!.map((t) => (
              <li key={t.id} className="rounded-md bg-[var(--muted)] px-3 py-2">
                <p className="font-mono text-xs">
                  {t.id} · {t.tool}({Object.entries(t.args).map(([k, v]) => `${k}=${String(v)}`).join(", ")})
                </p>
                <p className="mt-1 whitespace-pre-wrap break-words text-xs text-[var(--muted-foreground)]">{t.text}</p>
              </li>
            ))}
          </ul>
        </details>
      )}

      {(report.validation?.length ?? 0) > 0 && (
        <div className="mt-4 flex gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs">
          <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
          <div>
            <p className="font-medium">Corrected before showing</p>
            <ul className="mt-0.5 list-disc pl-4 text-[var(--muted-foreground)]">
              {report.validation!.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          </div>
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t pt-3 text-xs text-[var(--muted-foreground)]">
        <span>
          {[report.provider, report.model].filter(Boolean).join(" · ") || "AI"} · {report.tool_calls_used ?? 0} lookups
          {run.llm_trace_id ? ` · Langfuse trace ${run.llm_trace_id}` : ""}
        </span>
        <Button variant="ghost" size="sm" onClick={write} disabled={rewrite.isPending}>
          {rewrite.isPending ? <Spinner /> : <RefreshCw aria-hidden />}
          Rewrite report
        </Button>
      </div>
    </Box>
  );
}

function FixRow({ runId, fix }: { runId: string; fix: RcaFix }) {
  const propose = useProposeFix(runId);
  const toast = useToast();
  if (!fix.proposable) {
    return <p className="mt-1.5 text-sm">{fix.title}</p>;
  }
  return (
    <div className="mt-2 rounded-md border p-3">
      <p className="text-sm">{fix.title}</p>
      <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
        Proposing creates an approval request with a dry-run diff. Nothing changes until an engineer approves it.
      </p>
      <Button
        className="mt-2"
        size="sm"
        onClick={() =>
          propose.mutate(fix.id, {
            onSuccess: () => toast({ kind: "ok", message: "Fix proposed. It's waiting for approval." }),
          })
        }
        disabled={propose.isPending}
      >
        {propose.isPending && <Spinner />}
        Propose this fix
      </Button>
      <div className="mt-2">
        <FormError error={propose.error} fallback="The fix could not be proposed." />
      </div>
    </div>
  );
}

function Box({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border bg-[var(--card)] p-4">{children}</div>;
}
