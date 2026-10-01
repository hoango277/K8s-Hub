"use client";

import { useState } from "react";
import Link from "next/link";
import { ClipboardCheck, Inbox, MessagesSquare } from "lucide-react";

import { ApprovalCard } from "@/components/chat/approval-card";
import { ErrorPanel, LoadingRow } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useApprovals } from "@/hooks/use-approvals";
import { useCurrentUser } from "@/hooks/use-auth";
import { hasRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { ApprovalStatus } from "@/types/approval";

const FILTERS: { id: ApprovalStatus | null; label: string; empty: string }[] = [
  {
    id: "pending",
    label: "Waiting",
    empty: "Nothing is waiting for a decision. When the assistant proposes a change, it appears here.",
  },
  { id: "executed", label: "Executed", empty: "No approved change has run yet." },
  { id: "failed", label: "Failed", empty: "No approved change has failed." },
  { id: "rejected", label: "Rejected", empty: "No change has been rejected." },
  { id: "expired", label: "Expired", empty: "No proposal has expired without a decision." },
  { id: null, label: "All", empty: "The assistant hasn't proposed any change yet." },
];

export function ApprovalsPage() {
  const [filter, setFilter] = useState<ApprovalStatus | null>("pending");
  const { data: me } = useCurrentUser();
  const canDecide = me ? hasRole(me.role, ["engineer"]) : false;
  const { data, isLoading, error, refetch, fetchNextPage, hasNextPage, isFetchingNextPage } =
    useApprovals(filter);
  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const current = FILTERS.find((f) => f.id === filter)!;

  return (
    <div className="mx-auto max-w-4xl px-4 pb-16 pt-8 sm:px-6">
      <PageHeader
        icon={ClipboardCheck}
        title="Approvals"
        description={
          canDecide
            ? "Cluster changes the assistant proposed. Read the dry-run diff, then approve or reject — nothing runs before that."
            : "Cluster changes the assistant proposed, and what became of them. Engineers and admins decide; nothing runs before that."
        }
      />

      <div role="group" aria-label="Filter by status" className="mb-6 flex flex-wrap gap-1.5">
        {FILTERS.map((f) => {
          const active = f.id === filter;
          return (
            <button
              key={f.label}
              type="button"
              aria-pressed={active}
              onClick={() => setFilter(f.id)}
              className={cn(
                "h-8 rounded-md border px-3 text-sm outline-none transition",
                "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                active
                  ? "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
              )}
            >
              {f.label}
            </button>
          );
        })}
      </div>

      {isLoading ? (
        <LoadingRow label="Loading approvals…" />
      ) : error ? (
        <ErrorPanel title="Couldn't load approvals" error={error} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <EmptyState icon={Inbox} title={`No ${current.label.toLowerCase()} changes`} description={current.empty}>
          {filter === "pending" && (
            <Link
              href="/chat"
              className="inline-flex h-8 items-center gap-2 rounded-md border px-3 text-sm outline-none transition hover:bg-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <MessagesSquare aria-hidden className="size-4" />
              Open the chat
            </Link>
          )}
        </EmptyState>
      ) : (
        <div className="space-y-4">
          <ul className="space-y-4">
            {items.map((a) => (
              <li key={a.id}>
                <ApprovalCard approvalId={a.id} />
              </li>
            ))}
          </ul>
          {hasNextPage && (
            <div className="flex justify-center">
              <Button variant="outline" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
                {isFetchingNextPage && <Spinner />}
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
