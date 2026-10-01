"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type { Approval, ApprovalPage, ApprovalStatus } from "@/types/approval";

const PAGE = 20;

/** How often to re-read an approval: fast while it runs, slower while it waits
 * (someone else may decide it on the Approvals page), never once it's final. */
function pollInterval(a: Approval | undefined): number | false {
  if (!a) return false;
  if (a.status === "executing") return 2_000;
  if (a.status === "pending") return 15_000;
  return false;
}

export function useApproval(id: string | null | undefined) {
  return useQuery({
    queryKey: qk.approvals.detail(id ?? ""),
    queryFn: () => api.get<Approval>(`/approvals/${id}`),
    enabled: Boolean(id),
    refetchInterval: (q) => pollInterval(q.state.data),
  });
}

/** The queue and history, newest first; `status` null means everything. */
export function useApprovals(status: ApprovalStatus | null) {
  return useInfiniteQuery({
    queryKey: qk.approvals.list(status),
    queryFn: ({ pageParam }) =>
      api.get<ApprovalPage>(
        `/approvals?limit=${PAGE}&offset=${pageParam}${status ? `&status=${status}` : ""}`,
      ),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    // New proposals arrive from any chat: keep the queue current.
    refetchInterval: 20_000,
  });
}

/** Pending count for the sidebar badge. */
export function useApprovalSummary(enabled = true) {
  return useQuery({
    queryKey: qk.approvals.summary,
    queryFn: () => api.get<{ pending: number }>("/approvals/summary"),
    enabled,
    refetchInterval: 30_000,
  });
}

/** A decision changes the approval, the queue, the badge — and adds a note to
 * the conversation the change came from. */
function useDecision<TVars>(fn: (vars: TVars) => Promise<Approval>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (a) => {
      qc.setQueryData(qk.approvals.detail(a.id), a);
      void qc.invalidateQueries({ queryKey: qk.approvals.all });
      if (a.thread_id) void qc.invalidateQueries({ queryKey: qk.threads.detail(a.thread_id) });
    },
  });
}

export function useApprove() {
  return useDecision((id: string) => api.post<Approval>(`/approvals/${id}/approve`));
}

export function useReject() {
  return useDecision(({ id, reason }: { id: string; reason: string }) =>
    api.post<Approval>(`/approvals/${id}/reject`, { reason }),
  );
}

export function useReverify() {
  return useDecision((id: string) => api.post<Approval>(`/approvals/${id}/verify`));
}
