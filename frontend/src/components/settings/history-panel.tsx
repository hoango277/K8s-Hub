"use client";

import { format, formatDistanceToNow } from "date-fns";
import { History } from "lucide-react";

import { FIELDS, formatValue } from "@/components/settings/meta";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { useSettingsHistory } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import type { SettingChange } from "@/types/settings";

/** Read-only, newest first. Keys are never shown — only that they changed. */
export function HistoryPanel() {
  const { data, isLoading, error, fetchNextPage, hasNextPage, isFetchingNextPage, refetch } =
    useSettingsHistory();
  const items = data?.pages.flatMap((p) => p.items) ?? [];

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]">
        <Spinner /> Loading history…
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4 text-sm">
        <p className="font-medium text-[var(--destructive)]">Couldn&apos;t load the history</p>
        <p className="mt-1 text-[var(--muted-foreground)]">
          {error instanceof ApiError ? error.message : "Check that the backend is running, then try again."}
        </p>
        <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
          Try again
        </Button>
      </div>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        icon={History}
        title="No changes yet"
        description="Every time a setting is saved, reset or reloaded here, it shows up in this list with who did it and when."
      />
    );
  }

  return (
    <div className="space-y-4">
      <ol className="divide-y rounded-lg border">
        {items.map((c) => (
          <li key={c.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-3">
            <p className="min-w-0 text-sm">{describe(c)}</p>
            <p className="shrink-0 text-xs text-[var(--muted-foreground)]">
              {c.actor_email}
              <span aria-hidden className="mx-1.5">
                ·
              </span>
              <time dateTime={c.changed_at} title={format(new Date(c.changed_at), "PPpp")}>
                {formatDistanceToNow(new Date(c.changed_at), { addSuffix: true })}
              </time>
            </p>
          </li>
        ))}
      </ol>
      {hasNextPage && (
        <div className="flex justify-center">
          <Button variant="outline" size="sm" onClick={() => void fetchNextPage()} disabled={isFetchingNextPage}>
            {isFetchingNextPage ? <Spinner /> : null}
            Show older changes
          </Button>
        </div>
      )}
    </div>
  );
}

function Name({ field }: { field: string }) {
  return <strong className="font-medium">{FIELDS[field]?.label ?? field}</strong>;
}

function Val({ field, value }: { field: string; value: unknown }) {
  return <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-xs">{formatValue(field, value)}</code>;
}

function describe(c: SettingChange): React.ReactNode {
  if (c.action === "reload_env") return "Reloaded the defaults from the .env file";
  if (!c.field) return c.action;

  const isKey = c.secret;
  switch (c.action) {
    case "update":
      return isKey ? (
        <>
          Replaced the <Name field={c.field} /> API key
        </>
      ) : (
        <>
          Changed <Name field={c.field} /> from <Val field={c.field} value={c.old_value} /> to{" "}
          <Val field={c.field} value={c.new_value} />
        </>
      );
    case "restore":
      return isKey ? (
        <>
          Removed the <Name field={c.field} /> key saved here (now uses .env)
        </>
      ) : (
        <>
          Reset <Name field={c.field} /> to the default <Val field={c.field} value={c.new_value} />
        </>
      );
    case "reset_all":
      return isKey ? (
        <>
          Reset all settings — removed the <Name field={c.field} /> key saved here
        </>
      ) : (
        <>
          Reset all settings — <Name field={c.field} /> back to <Val field={c.field} value={c.new_value} />
        </>
      );
    default:
      return c.action;
  }
}
