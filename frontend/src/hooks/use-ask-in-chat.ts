"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";

import { errorMessage } from "@/components/skills/shared";
import { useToast } from "@/components/ui/toast";
import { useCreateThread } from "@/hooks/use-threads";
import { api } from "@/lib/api";
import { saveDraft } from "@/lib/chat-drafts";
import { qk } from "@/lib/query-keys";
import type { Thread } from "@/types/chat";

/**
 * "Ask in chat" from a diagnosis: open the user's conversation about that run —
 * the latest one, or a new one — and optionally leave a question in the composer.
 *
 * Reusing the existing thread keeps one conversation per diagnosis instead of a
 * new "Diagnosis: …" entry on every click. The backend refuses a run the user
 * may not see (404), shown as a toast.
 */
export function useAskInChat() {
  const qc = useQueryClient();
  const create = useCreateThread();
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function ask(runId: string, draft?: string) {
    setBusy(true);
    try {
      const threads = await qc.fetchQuery({
        queryKey: qk.threads.list(false),
        queryFn: () => api.get<Thread[]>("/chat/threads?include_archived=false"),
      });
      const thread = threads.find((t) => t.rca_run_id === runId) ?? (await create.mutateAsync({ rca_run_id: runId }));
      if (draft) saveDraft(thread.id, draft);
      // Stays "busy" on success: the page is about to change, a second click would open it twice.
      router.push(`/chat?thread=${thread.id}`);
    } catch (e) {
      toast({ kind: "error", message: errorMessage(e, "Couldn't open the chat. Try again.") });
      setBusy(false);
    }
  }

  return { ask, busy };
}
