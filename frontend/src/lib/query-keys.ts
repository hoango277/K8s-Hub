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
  settings: {
    all: ["settings"] as const,
    view: ["settings", "view"] as const,
    history: ["settings", "history"] as const,
    status: ["settings", "status"] as const,
  },
  auth: {
    me: ["auth", "me"] as const,
  },
  users: {
    all: ["users"] as const,
  },
  skills: {
    all: ["skills"] as const,
    list: ["skills", "list"] as const,
    /** Also the prefix of every file of that skill, so invalidating it refreshes those too. */
    detail: (name: string) => ["skills", "detail", name] as const,
    file: (name: string, path: string) => ["skills", "detail", name, "file", path] as const,
    /** Every run list, whatever the filter. */
    runsAll: ["skills", "runs"] as const,
    runs: (skill: string | null) => ["skills", "runs", skill] as const,
  },
  tools: {
    all: ["tools"] as const,
    list: ["tools", "list"] as const,
    runs: ["tools", "runs"] as const,
    templates: ["tools", "templates"] as const,
    servers: ["tools", "servers"] as const,
  },
  approvals: {
    all: ["approvals"] as const,
    list: (status: string | null) => ["approvals", "list", status] as const,
    detail: (id: string) => ["approvals", "detail", id] as const,
    summary: ["approvals", "summary"] as const,
  },
} as const;
