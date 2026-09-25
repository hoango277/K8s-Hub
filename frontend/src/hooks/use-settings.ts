"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { SettingsPatch, SettingsView } from "@/types/settings";

const KEY = ["settings"] as const;

export function useSettings() {
  return useQuery({
    queryKey: KEY,
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
    // The server returns the new state; use it directly instead of refetching.
    onSuccess: (data) => qc.setQueryData(KEY, data),
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
