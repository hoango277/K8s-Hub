"use client";

import { format, formatDistanceToNow } from "date-fns";
import {
  Activity,
  Box,
  ChevronRight,
  CircleCheck,
  CircleDashed,
  CircleX,
  GitCommitHorizontal,
  Gauge,
  Link2,
  type LucideIcon,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import type { EventCategory, RcaEntity, RcaRunSummary, RcaTrigger, Verdict } from "@/types/rca";

/**
 * How each kind of event reads at a glance, by the colour rules
 * (docs/ke-hoach/he-mau-giao-dien.md): a symptom is a failure (crimson), resource
 * pressure needs attention (mustard), and a change gets the accent because it is
 * the usual root cause — the first thing to look at. State and dependency events
 * carry no good/bad meaning, so they stay neutral. Colour sits on small marks
 * (icon, graph bar, badge) only — never on whole cards.
 */
export const CATEGORY: Record<
  EventCategory,
  {
    label: string;
    tone: "danger" | "warning" | "accent" | "neutral";
    icon: LucideIcon;
    /** Icon colour. */
    text: string;
    /** Bar of a graph node and the legend swatch. */
    bar: string;
  }
> = {
  change: {
    label: "Change", tone: "accent", icon: GitCommitHorizontal,
    text: "text-[var(--brand)]", bar: "fill-[var(--brand)]",
  },
  resource: {
    label: "Resource", tone: "warning", icon: Gauge,
    text: "text-[var(--warning)]", bar: "fill-[var(--warning)]",
  },
  state: {
    label: "State", tone: "neutral", icon: Box,
    text: "text-[var(--muted-foreground)]", bar: "fill-[var(--muted-foreground)]",
  },
  symptom: {
    label: "Symptom", tone: "danger", icon: Activity,
    text: "text-[var(--destructive)]", bar: "fill-[var(--destructive)]",
  },
  dependency: {
    label: "Dependency", tone: "neutral", icon: Link2,
    text: "text-[var(--muted-foreground)]", bar: "fill-[var(--border)]",
  },
};

export const TRIGGER: Record<RcaTrigger, string> = {
  manual: "Started here",
  chat: "From chat",
  alert: "From alert",
  scan: "Periodic scan",
};

export const VERDICT: Record<Verdict, { label: string; tone: "success" | "danger" | "neutral" }> = {
  confirmed: { label: "AI confirmed", tone: "success" },
  refuted: { label: "AI refuted", tone: "danger" },
  unclear: { label: "AI unsure", tone: "neutral" },
};

/**
 * Numbered so a step can be referred to ("did you do 2?"). Neutral on purpose:
 * three cards × three steps of accent would spend the accent everywhere.
 */
export function Steps({ steps, label }: { steps: string[]; label: string }) {
  return (
    <ol aria-label={label} className="mt-1.5 space-y-1.5">
      {steps.map((s, i) => (
        <li key={s} className="flex gap-2 text-sm">
          <span
            aria-hidden
            className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-[var(--muted)] text-[11px] font-semibold text-[var(--foreground)] ring-1 ring-inset ring-[var(--border)]"
          >
            {i + 1}
          </span>
          <span>{s}</span>
        </li>
      ))}
    </ol>
  );
}

/**
 * Collapsed by default: evidence, lookups and corrections are there for whoever
 * needs to check the result, but most readers only want the cause and the steps.
 */
export function Fold({
  summary,
  children,
  className,
}: {
  summary: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <details className={cn("group", className)}>
      <summary
        className={cn(
          "flex min-h-8 cursor-pointer list-none items-center gap-1.5 rounded-md text-sm text-[var(--muted-foreground)] outline-none",
          "hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] [&::-webkit-details-marker]:hidden",
        )}
      >
        <ChevronRight
          aria-hidden
          className="size-4 shrink-0 transition-transform group-open:rotate-90 motion-reduce:transition-none"
        />
        {summary}
      </summary>
      <div className="mt-1 pl-5.5">{children}</div>
    </details>
  );
}

/** "Deployment shop/api", "Pod shop/api-7d9f-x", "Node lab1". */
export function entityLabel(e: RcaEntity): string {
  const kind = e.sub || e.kind;
  return `${kind} ${e.namespace ? `${e.namespace}/` : ""}${e.name}`;
}

export function clock(iso: string): string {
  return format(new Date(iso), "HH:mm:ss");
}

export function when(iso: string): string {
  return formatDistanceToNow(new Date(iso), { addSuffix: true });
}

export function windowLabel(start: string, end: string): string {
  const minutes = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 60_000);
  const span = minutes >= 120 && minutes % 60 === 0 ? `${minutes / 60} h` : `${minutes} min`;
  return `${span} up to ${format(new Date(end), "MMM d, HH:mm")}`;
}

export function targetLabel(run: Pick<RcaRunSummary, "namespace" | "target_kind" | "target_name">): string {
  if (run.namespace === "*") return "the whole cluster";
  return run.target_name ? `${run.namespace}/${run.target_name}` : `namespace ${run.namespace}`;
}

/** "Workload/langfuse/langfuse-worker" → "langfuse/langfuse-worker". */
export function keyLabel(key: string): string {
  const [, ns, name] = key.split("/");
  return ns && ns !== "-" ? `${ns}/${name}` : name ?? key;
}

/** Status of a run, including its AI report. */
export function RunStatus({ run }: { run: Pick<RcaRunSummary, "status" | "report_status"> }) {
  if (run.status === "pending" || run.status === "running") {
    return (
      <Badge tone="accent" className="gap-1.5">
        <Spinner className="size-3" label="Analysing" /> Analysing
      </Badge>
    );
  }
  if (run.status === "failed") {
    return (
      <Badge tone="danger" className="gap-1">
        <CircleX aria-hidden className="size-3.5" /> Failed
      </Badge>
    );
  }
  if (run.report_status === "running") {
    return (
      <Badge tone="accent" className="gap-1.5">
        <Spinner className="size-3" label="Writing report" /> Writing report
      </Badge>
    );
  }
  return (
    <Badge tone="success" className="gap-1">
      <CircleCheck aria-hidden className="size-3.5" /> Done
    </Badge>
  );
}

export function StepIcon({ status }: { status: "running" | "done" | "error" }) {
  if (status === "running") return <Spinner className="size-4" label="In progress" />;
  if (status === "error") return <CircleX aria-label="Failed" className="size-4 text-[var(--destructive)]" />;
  return <CircleCheck aria-label="Done" className="size-4 text-[var(--success)]" />;
}

export function PendingIcon() {
  return <CircleDashed aria-hidden className="size-4 text-[var(--muted-foreground)]" />;
}
