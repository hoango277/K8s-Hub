"use client";

import { Bot, ListChecks, RefreshCw, Sparkles } from "lucide-react";

import { ApprovalCard } from "@/components/chat/approval-card";
import { Fold, Steps } from "@/components/rca/shared";
import { errorMessage } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useRewriteReport } from "@/hooks/use-rca";
import type { RcaRun } from "@/types/rca";

/**
 * The AI's answer in one or two sentences. Steps and fixes live on each cause
 * (hypotheses.tsx); how the AI got there is folded away for whoever checks it.
 */
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
          <span>The AI is checking the top causes. This takes up to a minute.</span>
        </div>
      </Box>
    );
  }

  if (run.report_status === "none" || run.report_status === "failed" || !report) {
    return (
      <Box>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">
            {run.report_status === "failed"
              ? "The AI report failed. The ranked causes below still hold."
              : "No AI report yet. The causes below come from causal rules alone."}
          </p>
          <Button variant="outline" size="sm" onClick={write} disabled={rewrite.isPending}>
            {rewrite.isPending ? <Spinner /> : <Bot aria-hidden />}
            {run.report_status === "failed" ? "Try again" : "Write AI report"}
          </Button>
        </div>
        {report?.error && <p className="mt-1 text-xs text-[var(--muted-foreground)]">{report.error}</p>}
      </Box>
    );
  }

  const lookups = report.tool_evidence ?? [];
  const corrections = report.validation ?? [];
  // Older reports had one list for the whole incident; newer ones put steps on each cause.
  const general = report.next_steps ?? [];
  const details = [
    `${lookups.length} lookup${lookups.length === 1 ? "" : "s"}`,
    corrections.length ? `${corrections.length} correction${corrections.length === 1 ? "" : "s"}` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Box highlight>
      <p className="eyebrow flex items-center gap-1.5 text-[var(--brand)]">
        <Sparkles aria-hidden className="size-4" /> AI summary
      </p>
      <p className="mt-1.5 text-base font-medium leading-relaxed">{report.summary}</p>

      {run.approval_id && (
        <div className="mt-3">
          <ApprovalCard approvalId={run.approval_id} />
        </div>
      )}

      {general.length > 0 && (
        <div className="mt-3">
          <p className="eyebrow flex items-center gap-1.5 text-[var(--muted-foreground)]">
            <ListChecks aria-hidden className="size-4" /> Next steps
          </p>
          <Steps steps={general} label="Next steps" />
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-start justify-between gap-2">
        <Fold summary={`How the AI checked this (${details})`} className="min-w-0 flex-1">
          <div className="space-y-3 pb-1 text-sm">
            {report.explanation && <p className="leading-relaxed">{report.explanation}</p>}
            {lookups.length > 0 && (
              <ul aria-label="Lookups" className="space-y-1.5">
                {lookups.map((t) => (
                  <li key={t.id} className="rounded-md bg-[var(--muted)] px-3 py-2">
                    <p className="font-mono text-xs">
                      {t.id} · {t.tool}({Object.entries(t.args).map(([k, v]) => `${k}=${String(v)}`).join(", ")})
                    </p>
                    <p className="mt-1 whitespace-pre-wrap break-words text-xs text-[var(--muted-foreground)]">
                      {t.text}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            {corrections.length > 0 && (
              <div>
                <p className="text-xs font-medium">Removed from the AI answer (not backed by the data)</p>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-[var(--muted-foreground)]">
                  {corrections.map((v) => (
                    <li key={v} className="break-words">
                      {v}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-xs text-[var(--muted-foreground)]">
              {[report.provider, report.model].filter(Boolean).join(" · ") || "AI"}
              {run.llm_trace_id ? ` · Langfuse trace ${run.llm_trace_id}` : ""}
            </p>
          </div>
        </Fold>
        <Button variant="ghost" size="sm" onClick={write} disabled={rewrite.isPending}>
          {rewrite.isPending ? <Spinner /> : <RefreshCw aria-hidden />}
          Rewrite
        </Button>
      </div>
    </Box>
  );
}

function Box({ children, highlight }: { children: React.ReactNode; highlight?: boolean }) {
  return (
    <div
      className={
        highlight
          ? // The page's key conclusion: an accent stripe and label on a plain card. A
            // tinted block next to red symptom cues read as one big alarm.
            "rounded-lg border border-l-4 border-l-[var(--brand)] bg-[var(--card)] p-4"
          : "rounded-lg border bg-[var(--card)] p-4"
      }
    >
      {children}
    </div>
  );
}
