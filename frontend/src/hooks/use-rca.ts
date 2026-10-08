"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type {
  RcaHypothesis,
  RcaRun,
  RcaRunCreate,
  RcaRunPage,
  RcaTargets,
  RcaTrigger,
  WorkloadRef,
} from "@/types/rca";

const PAGE = 20;

/** Still changing: the analysis or the AI report is in progress. */
export function isActive(run: Pick<RcaRun, "status" | "report_status"> | undefined): boolean {
  if (!run) return false;
  return run.status === "pending" || run.status === "running" || run.report_status === "running";
}

/**
 * One diagnosis. Progress is read by polling the run (its steps are stored in
 * the row), not the SSE endpoint: it survives a reload and needs no extra
 * connection handling, at the cost of ~1.5 s granularity on steps that take
 * seconds anyway.
 */
export function useRcaRun(id: string) {
  return useQuery({
    queryKey: qk.rca.detail(id),
    queryFn: () => api.get<RcaRun>(`/rca/runs/${id}`),
    refetchInterval: (q) => (isActive(q.state.data) ? 1_500 : false),
  });
}

export function useRcaRuns(trigger: RcaTrigger | null) {
  return useInfiniteQuery({
    queryKey: qk.rca.list(trigger),
    queryFn: ({ pageParam }) =>
      api.get<RcaRunPage>(`/rca/runs?limit=${PAGE}&offset=${pageParam}${trigger ? `&trigger=${trigger}` : ""}`),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
    // Runs started from the chat (or still running) show up without a reload.
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) => p.items.some((r) => isActive(r))) ? 3_000 : 20_000,
  });
}

export function useRcaTargets(enabled: boolean) {
  return useQuery({
    queryKey: qk.rca.targets,
    queryFn: () => api.get<RcaTargets>("/rca/targets"),
    enabled,
    staleTime: 60_000,
  });
}

export function useRcaWorkloads(namespace: string | null) {
  return useQuery({
    queryKey: qk.rca.workloads(namespace ?? ""),
    queryFn: () => api.get<WorkloadRef[]>(`/rca/targets/${namespace}/workloads`),
    enabled: Boolean(namespace),
    staleTime: 30_000,
  });
}

export function useStartRca() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RcaRunCreate) => api.post<RcaRun>("/rca/runs", body),
    onSuccess: (run) => {
      qc.setQueryData(qk.rca.detail(run.id), run);
      void qc.invalidateQueries({ queryKey: qk.rca.all });
    },
  });
}

export function useRewriteReport(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { provider?: string | null; model?: string | null }) =>
      api.post<RcaRun>(`/rca/runs/${id}/report`, body),
    onSuccess: (run) => qc.setQueryData(qk.rca.detail(id), run),
  });
}

export function useHypothesisFeedback(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ rank, correct }: { rank: number; correct: boolean }) =>
      api.post<RcaHypothesis>(`/rca/runs/${runId}/hypotheses/${rank}/feedback`, { correct }),
    onSuccess: (hyp) =>
      qc.setQueryData<RcaRun>(qk.rca.detail(runId), (run) =>
        run ? { ...run, hypotheses: run.hypotheses.map((h) => (h.rank === hyp.rank ? hyp : h)) } : run,
      ),
  });
}

export function useProposeFix(runId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (fixId: string) =>
      api.post<{ approval_id: string; title: string; status: string }>(
        `/rca/runs/${runId}/fixes/${encodeURIComponent(fixId)}/propose`,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.rca.detail(runId) });
      void qc.invalidateQueries({ queryKey: qk.approvals.all });
    },
  });
}
