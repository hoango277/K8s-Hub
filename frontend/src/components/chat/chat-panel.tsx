"use client";

import { useEffect, useState } from "react";
import { MessageSquarePlus, MessagesSquare, Trash2 } from "lucide-react";

import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { ModelPicker } from "@/components/chat/model-picker";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { useChatStream } from "@/hooks/use-chat-stream";
import { useModelSelection } from "@/hooks/use-models";
import {
  useChatTools,
  useCreateThread,
  useDeleteThread,
  useThread,
  useThreads,
} from "@/hooks/use-threads";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { cn } from "@/lib/utils";

/** Storage key for the open thread, so reloading the page keeps your place. */
const THREAD_KEY = "k8shub.thread";

export function ChatPanel() {
  // Thread the user just clicked in this session.
  const [clickedId, setClickedId] = useState<string | null>(null);

  // Thread from the previous visit.
  const [storedId, storeThread] = useLocalStorage(THREAD_KEY);

  // Thread waiting for delete confirmation.
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const threads = useThreads();

  // The open thread is DERIVED, not stored as its own state.
  //
  // Priority order, and `clickedId` must win IMMEDIATELY with no conditions:
  // it is only set right after clicking an existing thread or creating a new
  // one — both cases are guaranteed to exist. If it first had to appear in
  // `threads`, then while the list is refetching the screen would stay on the
  // old thread — clicking "New chat" would look like it did nothing.
  const threadList = threads.data;
  const threadId =
    clickedId ??
    (threadList
      ? storedId && threadList.some((t) => t.id === storedId)
        ? storedId
        : (threadList[0]?.id ?? null)
      : storedId);

  const detail = useThread(threadId);
  const tools = useChatTools();
  const create = useCreateThread();
  const remove = useDeleteThread();

  const llm = useModelSelection();
  const { live, isStreaming, send, stop } = useChatStream(threadId, {
    provider: llm.provider,
    model: llm.model,
  });

  useEffect(() => {
    if (threadId && threadId !== storedId) storeThread(threadId);
  }, [threadId, storedId, storeThread]);

  async function newThread() {
    const t = await create.mutateAsync();
    setClickedId(t.id);
  }

  async function confirmDelete() {
    const id = pendingDeleteId;
    setPendingDeleteId(null);
    if (!id) return;
    await remove.mutateAsync(id);
    if (id === clickedId) setClickedId(null);
  }

  const toolNames = tools.data?.tools.map((t) => t.name) ?? [];
  const pendingDeleteTitle = threadList?.find((t) => t.id === pendingDeleteId)?.title ?? "";

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r">
        <div className="p-2">
          <Button
            variant="outline"
            className="w-full justify-start"
            onClick={() => void newThread()}
            disabled={create.isPending}
          >
            <MessageSquarePlus aria-hidden />
            {create.isPending ? "Creating…" : "New chat"}
          </Button>
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
            {threads.isLoading &&
              [72, 56, 64, 48].map((w) => (
                <div key={w} aria-hidden className="px-2.5 py-2.5">
                  <div
                    className="h-3.5 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none"
                    style={{ width: `${w}%` }}
                  />
                </div>
              ))}

            {threads.error && (
              <div role="alert" className="mx-1 rounded-md bg-[var(--destructive)]/10 px-2.5 py-2 text-xs text-[var(--destructive)]">
                Couldn&apos;t load your chats.{" "}
                <button
                  type="button"
                  onClick={() => void threads.refetch()}
                  className="font-medium underline underline-offset-2"
                >
                  Try again
                </button>
              </div>
            )}

            {threadList?.length === 0 && (
              <p className="px-2.5 py-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
                No chats yet. Click “New chat” to start.
              </p>
            )}

            {threadList?.map((t) => (
              <div
                key={t.id}
                className={cn(
                  "group flex items-center rounded-lg transition",
                  t.id === threadId
                    ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                    : "hover:bg-[var(--accent)]/50",
                )}
              >
                <button
                  type="button"
                  onClick={() => setClickedId(t.id)}
                  className="min-w-0 flex-1 px-2.5 py-2 text-left text-sm"
                  title={t.title}
                >
                  <span className="block truncate">{t.title}</span>
                </button>

                <button
                  type="button"
                  onClick={() => setPendingDeleteId(t.id)}
                  aria-label={`Delete ${t.title}`}
                  title="Delete chat"
                  className={cn(
                    "mr-1.5 rounded p-1 opacity-0 transition",
                    "hover:text-[var(--destructive)] focus-visible:opacity-100",
                    "group-hover:opacity-100",
                  )}
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </button>
              </div>
            ))}
        </div>
      </aside>

      {/* Chat area */}
      <div className="flex min-w-0 flex-1 flex-col">
        {threadId ? (
          <>
            <div className="flex-1 overflow-y-auto">
              {detail.isLoading ? (
                <div className="flex h-full items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
                  <Spinner /> Loading chat…
                </div>
              ) : (
                <MessageList
                  messages={detail.data?.messages ?? []}
                  live={live}
                  toolNames={toolNames}
                  onSuggestion={isStreaming ? undefined : (q) => void send(q)}
                />
              )}
            </div>

            <Composer
              onSend={(c) => void send(c)}
              onStop={stop}
              isStreaming={isStreaming}
              toolbar={
                <ModelPicker
                  provider={llm.provider}
                  model={llm.model}
                  providers={llm.providers}
                  providerInfo={llm.providerInfo}
                  models={llm.models}
                  modelSource={llm.modelSource}
                  modelError={llm.modelError}
                  disabled={isStreaming}
                  onProviderChange={llm.setProvider}
                  onModelChange={llm.setModel}
                />
              }
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center px-6">
            <EmptyState
              icon={MessagesSquare}
              title="No chat open"
              description="Start a new chat to ask about your cluster, or pick an earlier one from the left."
              className="w-full max-w-lg"
            >
              <Button onClick={() => void newThread()} disabled={create.isPending}>
                <MessageSquarePlus aria-hidden />
                {create.isPending ? "Creating…" : "Start a chat"}
              </Button>
            </EmptyState>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingDeleteId !== null}
        destructive
        title="Delete this chat?"
        description={
          pendingDeleteTitle
            ? `“${pendingDeleteTitle}” and all of its messages and lookup history will be permanently deleted. This can't be undone.`
            : "All messages and lookup history will be permanently deleted. This can't be undone."
        }
        confirmLabel="Delete"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setPendingDeleteId(null)}
      />
    </div>
  );
}
