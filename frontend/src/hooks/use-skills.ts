"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, ApiError } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type {
  SkillCreate,
  SkillDetail,
  SkillFileContent,
  SkillRun,
  SkillRunPage,
  SkillSummary,
} from "@/types/skill";

const RUNS_PAGE = 20;

/** `/skills/<name>[/files/<path>]` with every segment encoded — file paths
 * contain slashes that must stay separators, not become part of a name. */
function skillUrl(name: string, filePath?: string): string {
  const base = `/skills/${encodeURIComponent(name)}`;
  if (filePath === undefined) return base;
  return `${base}/files/${filePath.split("/").map(encodeURIComponent).join("/")}`;
}

export function useSkills() {
  return useQuery({
    queryKey: qk.skills.list,
    queryFn: () => api.get<SkillSummary[]>("/skills"),
  });
}

export function useSkill(name: string) {
  return useQuery({
    queryKey: qk.skills.detail(name),
    queryFn: () => api.get<SkillDetail>(skillUrl(name)),
    // A 404 won't fix itself by retrying; show "not found" right away.
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
  });
}

export function useSkillFile(name: string, path: string | null) {
  return useQuery({
    queryKey: qk.skills.file(name, path ?? ""),
    queryFn: () => api.get<SkillFileContent>(skillUrl(name, path!)),
    enabled: path !== null,
  });
}

/** Put a fresh SkillDetail in the cache and patch its list row, so the page
 * updates at once without refetching the whole catalog. */
function useApplyDetail() {
  const qc = useQueryClient();
  return (detail: SkillDetail) => {
    qc.setQueryData(qk.skills.detail(detail.name), detail);
    qc.setQueryData<SkillSummary[]>(qk.skills.list, (prev) => {
      if (!prev) return prev;
      const summary: SkillSummary = {
        name: detail.name,
        description: detail.description,
        source: detail.source,
        enabled: detail.enabled,
        files: detail.files,
      };
      return prev.some((s) => s.name === detail.name)
        ? prev.map((s) => (s.name === detail.name ? summary : s))
        : [...prev, summary].sort((a, b) => a.name.localeCompare(b.name));
    });
  };
}

export function useCreateSkill() {
  const apply = useApplyDetail();
  return useMutation({
    mutationFn: (payload: SkillCreate) => api.post<SkillDetail>("/skills", payload),
    onSuccess: apply,
  });
}

export function useImportSkill() {
  const qc = useQueryClient();
  const apply = useApplyDetail();
  return useMutation({
    mutationFn: ({ file, replace }: { file: File; replace: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      return api.upload<SkillDetail>(`/skills/import?replace=${replace}`, form);
    },
    onSuccess: (detail) => {
      // A replaced skill may have lost or changed files that are still cached.
      void qc.invalidateQueries({ queryKey: qk.skills.detail(detail.name) });
      apply(detail);
    },
  });
}

export function useSetSkillEnabled() {
  const apply = useApplyDetail();
  return useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) =>
      api.patch<SkillDetail>(skillUrl(name), { enabled }),
    onSuccess: apply,
  });
}

export function useDeleteSkill() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.del<null>(skillUrl(name)),
    onSuccess: (_data, name) => {
      qc.setQueryData<SkillSummary[]>(qk.skills.list, (prev) => prev?.filter((s) => s.name !== name));
      // Don't removeQueries(detail) here: the detail page is still mounted when
      // this runs, so its observer would refetch the deleted skill at once (a
      // 404 in the console) before the page navigates away. Left alone, the
      // entry is garbage-collected after the page unmounts.
    },
  });
}

export function useWriteSkillFile() {
  const qc = useQueryClient();
  const apply = useApplyDetail();
  return useMutation({
    mutationFn: ({ name, path, text }: { name: string; path: string; text: string }) =>
      api.put<SkillDetail>(skillUrl(name, path), { text }),
    onSuccess: (detail, { path, text }) => {
      apply(detail);
      qc.setQueryData<SkillFileContent>(qk.skills.file(detail.name, path), {
        path,
        text,
        size: new TextEncoder().encode(text).length,
      });
    },
  });
}

export function useDeleteSkillFile() {
  const qc = useQueryClient();
  const apply = useApplyDetail();
  return useMutation({
    mutationFn: ({ name, path }: { name: string; path: string }) =>
      api.del<SkillDetail>(skillUrl(name, path)),
    onSuccess: (detail, { path }) => {
      apply(detail);
      qc.removeQueries({ queryKey: qk.skills.file(detail.name, path) });
    },
  });
}

export function useRunSkillScript() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, script, args }: { name: string; script: string; args: string[] }) =>
      api.post<SkillRun>(`${skillUrl(name)}/run`, { script, args }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.skills.runsAll }),
  });
}

/** Script run history, newest first, 20 rows at a time. `skill` null = every skill. */
export function useSkillRuns(skill: string | null) {
  return useInfiniteQuery({
    queryKey: qk.skills.runs(skill),
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(RUNS_PAGE), offset: String(pageParam) });
      if (skill) params.set("skill", skill);
      return api.get<SkillRunPage>(`/skills/runs?${params}`);
    },
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

export function useExportSkill() {
  return useMutation({
    mutationFn: (name: string) => api.download(`${skillUrl(name)}/export`, `${name}.zip`),
  });
}
