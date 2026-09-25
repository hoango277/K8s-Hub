"use client";

import { CircleAlert, CircleCheck, CircleMinus, RefreshCw } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useConnectionStatus } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { ConnectionStatus } from "@/types/settings";

/**
 * Read-only: can the backend reach the services it depends on?
 *
 * Addresses come from .env on the server and are deliberately not editable
 * here — this answers "is it up?", not "where is it?".
 */
export function ConnectionsPanel() {
  const { data, isLoading, isFetching, error, refetch, dataUpdatedAt } = useConnectionStatus();

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-[var(--muted-foreground)]" aria-live="polite">
          {dataUpdatedAt
            ? `Checked at ${new Date(dataUpdatedAt).toLocaleTimeString()} · refreshes every 30 seconds`
            : "Checking…"}
        </p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          <RefreshCw aria-hidden className={cn(isFetching && "k8s-spin")} />
          Check again
        </Button>
      </div>

      {error ? (
        <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4 text-sm">
          <p className="font-medium text-[var(--destructive)]">Couldn&apos;t run the checks</p>
          <p className="mt-1 text-[var(--muted-foreground)]">
            {error instanceof ApiError ? error.message : "The backend didn't answer. Check that it is running."}
          </p>
        </div>
      ) : (
        <ul className="divide-y rounded-lg border">
          {isLoading
            ? Array.from({ length: 4 }, (_, i) => <SkeletonItem key={i} />)
            : data?.map((c) => <ConnectionItem key={c.id} c={c} />)}
        </ul>
      )}
    </div>
  );
}

function ConnectionItem({ c }: { c: ConnectionStatus }) {
  const state = c.ok === null ? "off" : c.ok ? "up" : "down";
  const Icon = state === "up" ? CircleCheck : state === "down" ? CircleAlert : CircleMinus;
  return (
    <li className="flex flex-wrap items-start gap-3 p-4">
      <Icon
        aria-hidden
        className={cn(
          "mt-0.5 size-5 shrink-0",
          state === "up" && "text-emerald-600 dark:text-emerald-400",
          state === "down" && "text-[var(--destructive)]",
          state === "off" && "text-[var(--muted-foreground)]",
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">{c.name}</span>
          {/* Colour always comes with a word — never colour alone. */}
          {state === "up" && <Badge tone="success">Connected</Badge>}
          {state === "down" && <Badge tone="danger">Unreachable</Badge>}
          {state === "off" && <Badge>Disabled</Badge>}
          {c.version && <span className="text-xs text-[var(--muted-foreground)]">{c.version}</span>}
        </div>
        <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">{c.purpose}</p>
        <p className="mt-1 truncate font-mono text-[11px] text-[var(--muted-foreground)]" title={c.target}>
          {c.target}
        </p>
        {c.detail && (
          <p
            className={cn(
              "mt-2 break-words text-xs",
              state === "down" ? "text-[var(--destructive)]" : "text-[var(--muted-foreground)]",
            )}
          >
            {c.detail}
          </p>
        )}
      </div>
      {c.latency_ms !== null && (
        <span className="shrink-0 text-xs tabular-nums text-[var(--muted-foreground)]">{c.latency_ms} ms</span>
      )}
    </li>
  );
}

function SkeletonItem() {
  return (
    <li aria-hidden className="flex items-start gap-3 p-4">
      <div className="size-5 animate-pulse rounded-full bg-[var(--muted)] motion-reduce:animate-none" />
      <div className="flex-1 space-y-2">
        <div className="h-3.5 w-32 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
        <div className="h-3 w-56 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
      </div>
    </li>
  );
}
