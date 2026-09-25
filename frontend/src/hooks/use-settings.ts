"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type { ModelCatalog } from "@/types/chat";
import type {
  ConnectionStatus,
  SettingChangePage,
  SettingsPatch,
  SettingsView,
} from "@/types/settings";

const HISTORY_PAGE = 20;

export function useSettings() {
  return useQuery({
    queryKey: qk.settings.view,
    queryFn: () => api.get<SettingsView>("/settings"),
    // Someone else may change the settings, so refetch when the tab regains focus.
    refetchOnWindowFocus: true,
    staleTime: 10_000,
  });
}

function useSettingsMutation<TVars>(fn: (vars: TVars) => Promise<SettingsView>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (data) => {
      // The server returns the new state; use it directly instead of refetching.
      qc.setQueryData(qk.settings.view, data);
      // Every change adds history rows, and a new API key changes which
      // models the chat panel can offer.
      void qc.invalidateQueries({ queryKey: qk.settings.history });
      void qc.invalidateQueries({ queryKey: ["chat"] });
    },
  });
}

export function useUpdateSettings() {
  return useSettingsMutation((patch: SettingsPatch) =>
    api.patch<SettingsView>("/settings", patch),
  );
}

export function useResetSettings() {
  return useSettingsMutation(() => api.post<SettingsView>("/settings/reset"));
}

export function useReloadEnv() {
  return useSettingsMutation(() => api.post<SettingsView>("/settings/reload-env"));
}

/** Change history, newest first, loaded 20 rows at a time. */
export function useSettingsHistory() {
  return useInfiniteQuery({
    queryKey: qk.settings.history,
    queryFn: ({ pageParam }) =>
      api.get<SettingChangePage>(`/settings/history?limit=${HISTORY_PAGE}&offset=${pageParam}`),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const loaded = pages.reduce((n, p) => n + p.items.length, 0);
      return loaded < last.total ? loaded : undefined;
    },
  });
}

/** Whether the database, Langfuse, Prometheus, Loki and Tempo answer right now. */
export function useConnectionStatus() {
  return useQuery({
    queryKey: qk.settings.status,
    queryFn: () => api.get<ConnectionStatus[]>("/settings/status"),
    // A status that is minutes old looks current but isn't — keep it fresh
    // while the section is open, and re-check on "Check again".
    refetchInterval: 30_000,
    staleTime: 0,
  });
}

/**
 * Ask the provider for its model list with the SAVED key, bypassing the
 * backend cache — the cheapest real call that proves the key works.
 */
export function useTestProviderKey() {
  return useMutation({
    mutationFn: (provider: string) =>
      api.get<ModelCatalog>(`/chat/models?provider=${provider}&refresh=true`),
  });
}
