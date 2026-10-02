"use client";

import { useId, useState } from "react";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import {
  ArrowRight,
  Ban,
  CircleCheck,
  CircleX,
  Clock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { ManifestDiff } from "@/components/chat/manifest-diff";
import { FormError, OutputBlock, errorMessage, textareaClass } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useApproval, useApprove, useReject, useReverify } from "@/hooks/use-approvals";
import { useCurrentUser } from "@/hooks/use-auth";
import { hasRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Approval, ApprovalStatus } from "@/types/approval";

const REASON_MAX = 1000;

const STATUS: Record<
  ApprovalStatus,
  { label: string; tone: "neutral" | "success" | "warning" | "danger" | "info"; icon: LucideIcon }
> = {
  pending: { label: "Awaiting approval", tone: "warning", icon: Clock },
  executing: { label: "Running", tone: "info", icon: RefreshCw },
  executed: { label: "Executed", tone: "success", icon: CircleCheck },
  failed: { label: "Failed", tone: "danger", icon: CircleX },
  rejected: { label: "Rejected", tone: "neutral", icon: Ban },
  expired: { label: "Expired", tone: "neutral", icon: Clock },
};

export function ApprovalStatusBadge({ status }: { status: ApprovalStatus }) {
  const s = STATUS[status];
  return (
    <Badge tone={s.tone}>
      <s.icon aria-hidden className="size-3" />
      {s.label}
    </Badge>
  );
}

export function DangerLevelBadge({ danger }: { danger: Approval["danger"] }) {
  return danger === "dangerous" ? (
    <Badge tone="danger">
      <ShieldAlert aria-hidden className="size-3" />
      Dangerous
    </Badge>
  ) : (
    <Badge tone="warning">
      <ShieldCheck aria-hidden className="size-3" />
      Review
    </Badge>
  );
}

function ago(iso: string | null): string {
  return iso ? formatDistanceToNow(new Date(iso), { addSuffix: true }) : "";
}

/** Collapsible block with a real button, so it works from the keyboard. */
function Section({
  title,
  defaultOpen = false,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((v) => !v)}
        className="rounded text-xs font-medium text-[var(--muted-foreground)] outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        {open ? "Hide" : "Show"} {title.toLowerCase()}
      </button>
      {open && (
        <div id={id} className="mt-1.5">
          {children}
        </div>
      )}
    </div>
  );
}

function RejectDialog({
  approval,
  open,
  onClose,
}: {
  approval: Approval;
  open: boolean;
  onClose: () => void;
}) {
  const reject = useReject();
  const toast = useToast();
  const [reason, setReason] = useState("");
  const titleId = useId();
  const fieldId = useId();
  const tooLong = reason.length > REASON_MAX;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (tooLong) return;
    reject.mutate(
      { id: approval.id, reason: reason.trim() },
      {
        onSuccess: () => {
          toast({
            kind: "ok",
            message: approval.thread_id
              ? "Change rejected. The assistant will be told in the chat."
              : "Change rejected.",
          });
          setReason("");
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId}>
      <form onSubmit={submit}>
        <DialogHeader
          id={titleId}
          icon={Ban}
          title="Reject this change"
          subtitle={approval.title}
          onClose={onClose}
          closeDisabled={reject.isPending}
        />
        <div className="space-y-3 px-5 py-4">
          <div className="space-y-1.5">
            <label htmlFor={fieldId} className="text-sm font-medium">
              Reason <span className="font-normal text-[var(--muted-foreground)]">(optional)</span>
            </label>
            <textarea
              id={fieldId}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              aria-invalid={tooLong}
              aria-describedby={`${fieldId}-hint`}
              className={textareaClass}
              placeholder="e.g. Scale during the maintenance window instead"
            />
            <p
              id={`${fieldId}-hint`}
              className={cn("text-xs", tooLong ? "text-[var(--destructive)]" : "text-[var(--muted-foreground)]")}
            >
              {tooLong
                ? `Keep it under ${REASON_MAX} characters (${reason.length} now).`
                : "Shown to the requester and to the assistant, so it doesn't propose the same thing again."}
            </p>
          </div>
          <FormError error={reject.error} fallback="Couldn't reject the change. Try again." />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={reject.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="destructive" disabled={reject.isPending || tooLong}>
            {reject.isPending && <Spinner />}
            Reject change
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}

/**
 * A proposed cluster change: what it does, the dry-run diff, and — for
 * engineers and admins — Approve / Reject. Reads the live status, so a
 * decision made elsewhere (another tab, the Approvals page) shows up here.
 */
export function ApprovalCard({
  approvalId,
  compact = false,
}: {
  approvalId: string;
  /** In the chat: diff collapsed, with a link to the Approvals page. */
  compact?: boolean;
}) {
  const { data: approval, isLoading, error, refetch } = useApproval(approvalId);
  const { data: me } = useCurrentUser();
  const canDecide = me ? hasRole(me.role, ["engineer"]) : false;
  const approve = useApprove();
  const reverify = useReverify();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [rejecting, setRejecting] = useState(false);

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border px-3 py-2.5 text-sm text-[var(--muted-foreground)]">
        <Spinner /> Loading the proposed change…
      </div>
    );
  }
  if (error || !approval) {
    return (
      <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 px-3 py-2.5 text-sm">
        <p className="text-[var(--destructive)]">
          {errorMessage(error, "Couldn't load the proposed change.")}
        </p>
        <Button variant="outline" size="sm" className="mt-2" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  const a = approval;
  const pending = a.status === "pending";
  const dangerous = a.danger === "dangerous";
  // Older rows predate the field; treat missing as "nothing flagged".
  const flags = a.risk_flags ?? [];
  const flagged = flags.length > 0;
  const flaggedTools = [...new Set(flags.map((f) => f.tool))].join(", ");

  function doApprove() {
    setConfirming(false);
    approve.mutate(a.id, {
      onSuccess: (r) =>
        toast(
          r.status === "executed"
            ? { kind: "ok", message: `Change executed. ${r.verify_message ?? ""}`.trim() }
            : { kind: "error", message: `The change failed: ${(r.result ?? "").split("\n")[0]}` },
        ),
      onError: (err) => toast({ kind: "error", message: errorMessage(err, "Couldn't approve the change.") }),
    });
  }

  return (
    <section
      aria-label={`Proposed change: ${a.title}`}
      className={cn(
        "k8s-fade-in space-y-3 rounded-lg border p-4 text-sm",
        pending && (dangerous ? "border-[var(--destructive)]/50" : "border-[var(--warning)]/50"),
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-[var(--muted-foreground)]">
            Proposed change
          </p>
          <p className="break-words font-medium">{a.title}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <DangerLevelBadge danger={a.danger} />
          <ApprovalStatusBadge status={a.status} />
        </div>
      </div>

      {flagged && (
        <div
          role="note"
          aria-label="Possible prompt injection"
          className="flex gap-2 rounded-md border border-[var(--destructive)]/50 bg-[var(--destructive)]/10 px-3 py-2 text-xs"
        >
          <ShieldAlert aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--destructive)]" />
          <div className="space-y-1">
            <p className="font-medium text-[var(--destructive)]">Possible prompt injection</p>
            <p className="leading-relaxed">
              Before proposing this, the assistant read text addressed to it in the output of{" "}
              <span className="font-mono">{flaggedTools}</span>. The request may come from cluster data, not
              from the user. Check that it matches what they asked.
            </p>
          </div>
        </div>
      )}

      <p className="text-xs text-[var(--muted-foreground)]">
        Requested by {a.requested_by_email} {ago(a.created_at)}
        {a.namespace && <> · namespace {a.namespace}</>}
        {pending && <> · expires {ago(a.expires_at)}</>}
      </p>

      {a.request_text && (
        <blockquote className="border-l-2 pl-3 text-xs text-[var(--muted-foreground)]">
          <span className="font-medium text-[var(--foreground)]">Asked: </span>
          <span className="line-clamp-3 whitespace-pre-wrap break-words">“{a.request_text}”</span>
        </blockquote>
      )}

      {a.command && (
        <pre className="overflow-x-auto rounded-md bg-[var(--muted)] px-3 py-2 font-mono text-xs">
          $ {a.command.join(" ")}
        </pre>
      )}

      {a.dry_run_output && (
        <p className="whitespace-pre-wrap break-words text-xs leading-relaxed text-[var(--muted-foreground)]">
          {a.dry_run_output}
        </p>
      )}

      {a.diff && (
        <Section title="Diff" defaultOpen={!compact && pending}>
          <ManifestDiff diff={a.diff} />
        </Section>
      )}

      {a.status === "executing" && (
        <p className="flex items-center gap-2 text-[var(--muted-foreground)]">
          <Spinner /> Running and checking the rollout…
        </p>
      )}

      {(a.status === "executed" || a.status === "failed") && (
        <div className="space-y-2">
          <p className="text-xs text-[var(--muted-foreground)]">
            Approved by {a.decided_by_email} {ago(a.decided_at)}
          </p>
          {a.result && <OutputBlock text={a.result} className="max-h-48" />}
          {a.verify_message && (
            <p
              className={cn(
                "flex items-start gap-2 text-sm",
                a.verify_ok ? "text-[var(--success)]" : "text-[var(--warning)]",
              )}
            >
              {a.verify_ok ? (
                <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
              ) : (
                <Clock aria-hidden className="mt-0.5 size-4 shrink-0" />
              )}
              <span>
                <span className="sr-only">{a.verify_ok ? "Verified: " : "Not verified yet: "}</span>
                {a.verify_message}
              </span>
            </p>
          )}
          {a.status === "executed" && a.verify_ok === false && canDecide && (
            <Button
              variant="outline"
              size="sm"
              disabled={reverify.isPending}
              onClick={() =>
                reverify.mutate(a.id, {
                  onSuccess: (r) =>
                    toast({ kind: r.verify_ok ? "ok" : "error", message: r.verify_message ?? "Checked." }),
                  onError: (err) => toast({ kind: "error", message: errorMessage(err, "Couldn't check again.") }),
                })
              }
            >
              {reverify.isPending ? <Spinner /> : <RefreshCw aria-hidden />}
              Check again
            </Button>
          )}
        </div>
      )}

      {a.status === "rejected" && (
        <p className="text-[var(--muted-foreground)]">
          Rejected by {a.decided_by_email} {ago(a.decided_at)}
          {a.reason && <>: “{a.reason}”</>}
        </p>
      )}

      {a.status === "expired" && (
        <p className="text-[var(--muted-foreground)]">
          Nobody decided in time. Ask the assistant to propose it again — it will run a fresh dry-run.
        </p>
      )}

      {pending &&
        (canDecide ? (
          <div className="flex flex-wrap items-center gap-2 border-t pt-3">
            <Button
              variant={dangerous ? "destructive" : "primary"}
              size="sm"
              disabled={approve.isPending}
              onClick={() => setConfirming(true)}
            >
              {approve.isPending ? <Spinner /> : <CircleCheck aria-hidden />}
              {approve.isPending ? "Running…" : "Approve and run"}
            </Button>
            <Button variant="outline" size="sm" disabled={approve.isPending} onClick={() => setRejecting(true)}>
              <Ban aria-hidden />
              Reject
            </Button>
          </div>
        ) : (
          <p className="border-t pt-3 text-xs text-[var(--muted-foreground)]">
            Waiting for an engineer or admin to approve. Nothing has changed on the cluster yet.
          </p>
        ))}

      {compact && (
        <Link
          href="/approvals"
          className="inline-flex items-center gap-1 rounded text-xs text-[var(--muted-foreground)] underline underline-offset-2 outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          Open the approval queue
          <ArrowRight aria-hidden className="size-3" />
        </Link>
      )}

      <ConfirmDialog
        open={confirming}
        title={dangerous ? "Run this dangerous change?" : "Run this change?"}
        description={`${a.title}. It runs now on the cluster, exactly as shown in the diff.${
          dangerous ? " This may be hard to undo." : ""
        }${flagged ? " It was flagged as a possible prompt injection — make sure the user asked for it." : ""}`}
        confirmLabel="Approve and run"
        destructive={dangerous || flagged}
        onConfirm={doApprove}
        onCancel={() => setConfirming(false)}
      />
      <RejectDialog approval={a} open={rejecting} onClose={() => setRejecting(false)} />
    </section>
  );
}
