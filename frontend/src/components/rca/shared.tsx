"use client";

import { format, formatDistanceToNow } from "date-fns";
import {
  Activity,
  Box,
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
import type { EventCategory, RcaEntity, RcaRunSummary, RcaTrigger, Verdict } from "@/types/rca";

/** How each kind of event reads at a glance. Changes stand out: they are the usual root cause. */
export const CATEGORY: Record<
  EventCategory,
  { label: string; tone: "danger" | "warning" | "info" | "violet" | "neutral"; icon: LucideIcon }
> = {
  change: { label: "Change", tone: "violet", icon: GitCommitHorizontal },
  resource: { label: "Resource", tone: "warning", icon: Gauge },
  state: { label: "State", tone: "info", icon: Box },
  symptom: { label: "Symptom", tone: "danger", icon: Activity },
  dependency: { label: "Dependency", tone: "neutral", icon: Link2 },
};

export const TRIGGER: Record<RcaTrigger, string> = {
  manual: "Started here",
  chat: "From chat",
  alert: "From alert",
  scan: "Periodic scan",
};

export const VERDICT: Record<Verdict, { label: string; tone: "success" | "danger" | "neutral" }> = {
  confirmed: { label: "Confirmed by AI", tone: "success" },
  refuted: { label: "Refuted by AI", tone: "danger" },
  unclear: { label: "Unclear", tone: "neutral" },
};

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
      <Badge tone="info" className="gap-1.5">
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
      <Badge tone="info" className="gap-1.5">
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
  return <CircleCheck aria-label="Done" className="size-4 text-emerald-600 dark:text-emerald-400" />;
}

export function PendingIcon() {
  return <CircleDashed aria-hidden className="size-4 text-[var(--muted-foreground)]" />;
}
