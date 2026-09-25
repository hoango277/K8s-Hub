/**
 * TanStack Query cache keys, gathered in one place.
 *
 * Typing key strings by hand at each call site is the fastest way to get the
 * "I fixed it but the screen didn't change" bug: the writer uses `["threads"]`,
 * the reader uses `["thread"]`, and the invalidation matches nothing.
 *
 * Keys are ordered from broad to narrow, so `invalidateQueries({queryKey:
 * qk.threads.all})` refreshes both the list and each individual thread.
 */

export const qk = {
  threads: {
    all: ["threads"] as const,
    /** Every list, whether or not it includes archived threads. */
    lists: ["threads", "list"] as const,
    list: (includeArchived = false) => ["threads", "list", includeArchived] as const,
    detail: (id: string) => ["threads", "detail", id] as const,
  },
  chat: {
    tools: ["chat", "tools"] as const,
    providers: ["chat", "providers"] as const,
    models: (provider: string) => ["chat", "models", provider] as const,
  },
  settings: ["settings"] as const,
  auth: {
    me: ["auth", "me"] as const,
  },
  users: {
    all: ["users"] as const,
  },
} as const;
