"use client";

import { useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { KeyRound, Plug, Plus, RefreshCw, Trash2 } from "lucide-react";

import { AddServerDialog } from "@/components/skills/add-server-dialog";
import { ErrorPanel, LoadingRow, SectionHeader, errorMessage } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import {
  useDeleteMcpServer,
  useMcpServers,
  useRefreshMcpServer,
  useSetMcpServerEnabled,
} from "@/hooks/use-tools";
import { cn } from "@/lib/utils";
import type { McpServer } from "@/types/tool";

export function McpServersPanel({ canEdit, description }: { canEdit: boolean; description: string }) {
  const { data: servers, isLoading, error, refetch } = useMcpServers();
  const setEnabled = useSetMcpServerEnabled();
  const refresh = useRefreshMcpServer();
  const remove = useDeleteMcpServer();
  const toast = useToast();

  const [addOpen, setAddOpen] = useState(false);
  const [removing, setRemoving] = useState<McpServer | null>(null);

  function toggle(s: McpServer, enabled: boolean) {
    setEnabled.mutate(
      { id: s.id, enabled },
      {
        onSuccess: () =>
          toast({
            kind: "ok",
            message: enabled ? `${s.name} is enabled.` : `${s.name} is disabled — its tools are out of the catalog.`,
          }),
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't update ${s.name}. Try again.`) }),
      },
    );
  }

  function reload(s: McpServer) {
    refresh.mutate(s.id, {
      onSuccess: (updated) =>
        updated.last_error
          ? toast({ kind: "error", message: `${s.name} didn't answer: ${updated.last_error}` })
          : toast({
              kind: "ok",
              message: `Refreshed ${s.name}: ${updated.tool_count} ${updated.tool_count === 1 ? "tool" : "tools"}.`,
            }),
      onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't refresh ${s.name}. Try again.`) }),
    });
  }

  function confirmRemove() {
    if (!removing) return;
    const s = removing;
    remove.mutate(s.id, {
      onSuccess: () => toast({ kind: "ok", message: `Removed ${s.name} and its tools.` }),
      onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't remove ${s.name}. Try again.`) }),
      onSettled: () => setRemoving(null),
    });
  }

  return (
    <>
      <SectionHeader
        title="MCP servers"
        description={description}
        actions={
          canEdit && servers && servers.length > 0 ? (
            <Button onClick={() => setAddOpen(true)}>
              <Plus aria-hidden />
              Add server
            </Button>
          ) : null
        }
      />

      {isLoading ? (
        <LoadingRow label="Loading servers…" />
      ) : error ? (
        <ErrorPanel title="Couldn't load MCP servers" error={error} onRetry={() => void refetch()} />
      ) : !servers || servers.length === 0 ? (
        <EmptyState
          icon={Plug}
          title="No MCP servers connected"
          description={
            <>
              An MCP server is an external service that offers tools over the Model Context Protocol — for example a
              ticketing system or a cloud API. Once connected, its tools appear under <strong>Tools</strong>,
              disabled and needing approval for every call, until an engineer reviews them.
            </>
          }
        >
          {canEdit ? (
            <Button size="sm" onClick={() => setAddOpen(true)}>
              <Plus aria-hidden />
              Add server
            </Button>
          ) : (
            <a href="#tools" className={buttonVariants({ variant: "outline", size: "sm" })}>
              See the built-in tools
            </a>
          )}
        </EmptyState>
      ) : (
        <ul className="space-y-3">
          {servers.map((s) => (
            <ServerRow
              key={s.id}
              server={s}
              canEdit={canEdit}
              refreshing={refresh.isPending && refresh.variables === s.id}
              toggling={setEnabled.isPending && setEnabled.variables?.id === s.id}
              onToggle={(enabled) => toggle(s, enabled)}
              onRefresh={() => reload(s)}
              onRemove={() => setRemoving(s)}
            />
          ))}
        </ul>
      )}

      {canEdit && (
        <>
          <AddServerDialog open={addOpen} onClose={() => setAddOpen(false)} />
          <ConfirmDialog
            open={removing !== null}
            destructive
            title={`Remove ${removing?.name ?? "this server"}?`}
            description="Its tools leave the catalog and the assistant can no longer call them. Their settings are lost; adding the server again starts them disabled."
            confirmLabel={remove.isPending ? "Removing…" : "Remove server"}
            onConfirm={confirmRemove}
            onCancel={() => !remove.isPending && setRemoving(null)}
          />
        </>
      )}
    </>
  );
}

function ServerStatus({ server }: { server: McpServer }) {
  if (!server.enabled) return <Badge tone="neutral">Disabled</Badge>;
  if (server.last_error) return <Badge tone="danger">Error</Badge>;
  return <Badge tone="success">Connected</Badge>;
}

function ServerRow({
  server: s,
  canEdit,
  refreshing,
  toggling,
  onToggle,
  onRefresh,
  onRemove,
}: {
  server: McpServer;
  canEdit: boolean;
  refreshing: boolean;
  toggling: boolean;
  onToggle: (enabled: boolean) => void;
  onRefresh: () => void;
  onRemove: () => void;
}) {
  return (
    <li className={cn("rounded-lg border p-4", !s.enabled && "bg-[var(--muted)]/40")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-mono text-sm font-semibold">{s.name}</p>
            <ServerStatus server={s} />
            {s.has_token && (
              <Badge tone="neutral">
                <KeyRound aria-hidden className="size-3" />
                Token set
              </Badge>
            )}
          </div>
          <p className="mt-1 break-all font-mono text-xs text-[var(--muted-foreground)]">{s.url}</p>
          <p className="mt-2 text-xs text-[var(--muted-foreground)]">
            {s.tool_count} {s.tool_count === 1 ? "tool" : "tools"}
            <span aria-hidden className="mx-1.5">
              ·
            </span>
            {s.refreshed_at ? (
              <time dateTime={s.refreshed_at} title={format(new Date(s.refreshed_at), "PPpp")}>
                Refreshed {formatDistanceToNow(new Date(s.refreshed_at), { addSuffix: true })}
              </time>
            ) : (
              "Never refreshed"
            )}
          </p>
        </div>

        {canEdit && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing || !s.enabled}>
              {refreshing ? <Spinner label="Refreshing" /> : <RefreshCw aria-hidden />}
              {refreshing ? "Refreshing…" : "Refresh"}
            </Button>
            <Button variant="ghost" size="icon" onClick={onRemove} aria-label={`Remove ${s.name}`}>
              <Trash2 aria-hidden />
            </Button>
            <Switch
              checked={s.enabled}
              pending={toggling}
              onCheckedChange={onToggle}
              aria-label={`${s.enabled ? "Disable" : "Enable"} ${s.name}`}
            />
          </div>
        )}
      </div>

      {s.enabled && s.last_error && (
        <p
          role="note"
          className="mt-3 break-words rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2 text-xs leading-relaxed text-[var(--destructive)]"
        >
          {s.last_error}
        </p>
      )}
    </li>
  );
}
