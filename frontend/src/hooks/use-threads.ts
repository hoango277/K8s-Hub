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
    // Lịch sử chỉ đổi khi chính người này gửi tin nhắn, nên không cần hỏi lại
    // mỗi lần quay về tab.
    refetchOnWindowFocus: false,
  });
}

export function useCreateThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<Thread>("/chat/threads", {}),
    onSuccess: (thread) => {
      // Hội thoại vừa tạo thì chắc chắn chưa có tin nhắn nào — điền thẳng vào
      // cache để khỏi phải gọi thêm một request chỉ để nhận về danh sách rỗng.
      // Mỗi lượt đi-về tới CSDL mất gần một giây, và đó đúng là khoảnh khắc
      // người dùng đang chờ màn hình phản hồi.
      qc.setQueryData(qk.threads.detail(thread.id), { ...thread, messages: [] });

      // Chỉ làm mới DANH SÁCH. Nếu dùng khoá gốc `threads` thì bản vừa điền ở
      // trên cũng bị làm mới theo, coi như công cốc.
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

/** CHƯA CÓ GIAO DIỆN đổi tên hội thoại — endpoint và hook đã sẵn sàng. */
export function useRenameThread() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) =>
      api.patch<Thread>(`/chat/threads/${id}`, { title }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.threads.all }),
  });
}

/** Công cụ trợ lý đang có — để hiện cho người dùng biết nó tra cứu được gì. */
export function useChatTools() {
  return useQuery({
    queryKey: qk.chat.tools,
    queryFn: () => api.get<{ tools: ToolInfo[] }>("/chat/tools"),
    staleTime: 5 * 60 * 1000,
  });
}
