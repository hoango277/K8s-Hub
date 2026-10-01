"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type {
  CustomTool,
  CustomToolFields,
  McpServer,
  McpServerCreate,
  Tool,
  ToolPatch,
  ToolRun,
  ToolRunPage,
} from "@/types/tool";

const RUNS_PAGE = 20;

export function useTools() {
  return useQuery({
    queryKey: qk.tools.list,
    queryFn: () => api.get<Tool[]>("/tools"),
  });
}

/** Tool state decides what the chat assistant may call, so the chat's own
 * tool list must be refreshed along with the catalog. */
function useInvalidateCatalog() {
  const qc = useQueryClient();
  return () => {
    void qc.invalidateQueries({ queryKey: qk.tools.list });
    void qc.invalidateQueries({ queryKey: qk.chat.tools });
  };
}

export function useUpdateTool() {
  const qc = useQueryClient();
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: ({ name, patch }: { name: string; patch: ToolPatch }) =>
      api.patch<Tool>(`/tools/${encodeURIComponent(name)}`, patch),
    onSuccess: (updated) => {
      qc.setQueryData<Tool[]>(qk.tools.list, (prev) => prev?.map((t) => (t.name === updated.name ? updated : t)));
      invalidate();
    },
  });
}

export function useRunTool() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, args }: { name: string; args: Record<string, unknown> }) =>
      api.post<ToolRun>(`/tools/${encodeURIComponent(name)}/run`, { args }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.tools.runs }),
  });
}

/** Tool run history, newest first (engineers see everyone's, users their own). */
export function useToolRuns() {
  return useInfiniteQuery({
    queryKey: qk.tools.runs,
    queryFn: ({ pageParam }) => api.get<ToolRunPage>(`/tools/runs?limit=${RUNS_PAGE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

/** Ready-made definitions (kubectl, helm) not created yet. Engineers only. */
export function useCustomToolTemplates(enabled: boolean) {
  return useQuery({
    queryKey: qk.tools.templates,
    queryFn: () => api.get<CustomTool[]>("/tools/custom/templates"),
    enabled,
  });
}

/** Custom tools change what the assistant can call: refresh the catalog, the
 * chat's tool list and the remaining templates. */
function useCustomMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.tools.templates });
      invalidate();
    },
  });
}

export function useCreateCustomTool() {
  return useCustomMutation((tool: CustomTool) => api.post<Tool>("/tools/custom", tool));
}

export function useUpdateCustomTool() {
  return useCustomMutation(({ name, fields }: { name: string; fields: CustomToolFields }) =>
    api.put<Tool>(`/tools/custom/${encodeURIComponent(name)}`, fields),
  );
}

export function useDeleteCustomTool() {
  return useCustomMutation((name: string) => api.del<null>(`/tools/custom/${encodeURIComponent(name)}`));
}

export function useMcpServers() {
  return useQuery({
    queryKey: qk.tools.servers,
    queryFn: () => api.get<McpServer[]>("/tools/mcp/servers"),
  });
}

/** Every server change can add, remove or re-read tools, so the catalog is
 * refreshed along with the server list. */
function useServerMutation<TVars, TResult>(fn: (vars: TVars) => Promise<TResult>) {
  const qc = useQueryClient();
  const invalidate = useInvalidateCatalog();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.tools.servers });
      invalidate();
    },
  });
}

export function useAddMcpServer() {
  return useServerMutation((payload: McpServerCreate) => api.post<McpServer>("/tools/mcp/servers", payload));
}

export function useSetMcpServerEnabled() {
  return useServerMutation(({ id, enabled }: { id: string; enabled: boolean }) =>
    api.patch<McpServer>(`/tools/mcp/servers/${id}`, { enabled }),
  );
}

export function useRefreshMcpServer() {
  return useServerMutation((id: string) => api.post<McpServer>(`/tools/mcp/servers/${id}/refresh`));
}

export function useDeleteMcpServer() {
  return useServerMutation((id: string) => api.del<null>(`/tools/mcp/servers/${id}`));
}
