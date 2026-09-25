"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import type { Thread, ThreadDetail, ToolInfo } from "@/types/chat";

export function useThreads(includeArchived = false) {
  return useQuery({
    queryKey: qk.threads.list(includeArchived),
    queryFn: () =>
      api.get<Thread[]>(
        `/chat/threads?include_archived=${includeArchived ? "true" : "false"}`,
      ),
  });
}

export function useThread(id: string | null) {
  return useQuery({
    queryKey: qk.threads.detail(id ?? ""),
    queryFn: () => api.get<ThreadDetail>(`/chat/threads/${id}`),
    enabled: Boolean(id),
    // History only changes when this same user sends a message, so there's no
    // need to refetch every time the tab regains focus.
    refetchOnWindowFocus: false,
  });
}

export function useCreateThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Thread>("/chat/threads", {}),
    onSuccess: (thread) => {
      // A freshly created thread certainly has no messages — seed the cache
      // directly to avoid an extra request just to receive an empty list.
      // Each round-trip to the DB takes nearly a second, and that is exactly
      // the moment the user is waiting for the screen to respond.
      qc.setQueryData(qk.threads.detail(thread.id), { ...thread, messages: [] });

      // Only refresh the LISTS. Using the root `threads` key would also
      // refresh the entry seeded above, undoing the work.
      void qc.invalidateQueries({ queryKey: qk.threads.lists });
    },
  });
}

export function useDeleteThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.del<void>(`/chat/threads/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.threads.all }),
  });
}

/** NO UI for renaming threads YET — the endpoint and hook are ready. */
export function useRenameThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch<Thread>(`/chat/threads/${id}`, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.threads.all }),
  });
}

/** The assistant's available tools — shown so users know what it can look up. */
export function useChatTools() {
  return useQuery({
    queryKey: qk.chat.tools,
    queryFn: () => api.get<{ tools: ToolInfo[] }>("/chat/tools"),
    staleTime: 5 * 60 * 1000,
  });
}
