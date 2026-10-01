"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  Boxes,
  Eye,
  Info,
  PenLine,
  Pencil,
  Play,
  Plug,
  Plus,
  ScrollText,
  Search,
  SearchX,
  Terminal,
  Trash2,
  TriangleAlert,
  Waypoints,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { CustomToolDialog } from "@/components/skills/custom-tool-dialog";
import { ErrorPanel, LoadingRow, SectionHeader, errorMessage } from "@/components/skills/shared";
import { ToolTryDialog } from "@/components/skills/tool-try-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { inputClass } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useDeleteCustomTool, useTools, useUpdateTool } from "@/hooks/use-tools";
import { cn } from "@/lib/utils";
import type { CustomTool, Tool, ToolCategory, ToolDanger } from "@/types/tool";

const CATEGORIES: { id: ToolCategory; label: string; icon: LucideIcon }[] = [
  { id: "kubernetes", label: "Kubernetes", icon: Boxes },
  { id: "metrics", label: "Metrics", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "traces", label: "Traces", icon: Waypoints },
  { id: "custom", label: "Custom tools", icon: Terminal },
  { id: "mcp", label: "External (MCP)", icon: Plug },
];

export const DANGER: Record<
  ToolDanger,
  { label: string; tone: "success" | "warning" | "danger"; icon: LucideIcon; description: string }
> = {
  read: {
    label: "Read",
    tone: "success",
    icon: Eye,
    description: "Only reads data. Runs as soon as it's called.",
  },
  write: {
    label: "Write",
    tone: "warning",
    icon: PenLine,
    description: "Proposes a change. Nothing runs until an engineer approves it.",
  },
  destructive: {
    label: "Destructive",
    tone: "danger",
    icon: TriangleAlert,
    description: "Proposes a change that is hard to undo. Nothing runs until an engineer approves it.",
  },
};

export function DangerBadge({ danger }: { danger: ToolDanger }) {
  const d = DANGER[danger];
  return (
    <Badge tone={d.tone}>
      <d.icon aria-hidden className="size-3" />
      {d.label}
    </Badge>
  );
}

function sourceLabel(tool: Tool): string {
  if (tool.mcp) return `MCP · ${tool.mcp.server}`;
  return tool.custom ? `Custom · ${tool.custom.command}` : "Built-in";
}

function hintText(hint: boolean | null): string {
  if (hint === true) return "The server says this tool only reads. Check the description before trusting that.";
  if (hint === false) return "The server says this tool can make changes.";
  return "The server doesn't say whether this tool changes anything.";
}

export function ToolsPanel({ canEdit, description }: { canEdit: boolean; description: string }) {
  const { data: tools, isLoading, error, refetch } = useTools();
  const update = useUpdateTool();
  const remove = useDeleteCustomTool();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [trying, setTrying] = useState<Tool | null>(null);
  // `undefined` = dialog closed, `null` = creating, a tool = editing it.
  const [editing, setEditing] = useState<CustomTool | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Tool | null>(null);
  // Turning approval OFF lets an external tool act on its own: confirm first.
  const [unguarding, setUnguarding] = useState<Tool | null>(null);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (tools ?? []).filter(
      (t) =>
        !q ||
        t.name.toLowerCase().includes(q) ||
        t.title.toLowerCase().includes(q) ||
        t.description.toLowerCase().includes(q),
    );
    return CATEGORIES.map((c) => ({ ...c, tools: list.filter((t) => t.category === c.id) })).filter(
      // The custom group stays visible to engineers even when empty: it's
      // where they learn they can add their own tools.
      (g) => g.tools.length > 0 || (g.id === "custom" && canEdit && !q),
    );
  }, [tools, query, canEdit]);

  const inChatCount = (tools ?? []).filter((t) => t.in_chat).length;

  function toggle(tool: Tool, enabled: boolean) {
    update.mutate(
      { name: tool.name, patch: { enabled } },
      {
        onSuccess: (t) => {
          const message = t.in_chat
            ? `${t.title} is enabled and available in chat.`
            : enabled
              ? `${t.title} is enabled${t.unavailable_reason ? `, but can't run yet: ${t.unavailable_reason}` : "."}`
              : `${t.title} is disabled.`;
          toast({ kind: "ok", message });
        },
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't update ${tool.title}. Try again.`) }),
      },
    );
  }

  function setApproval(tool: Tool, requiresApproval: boolean) {
    update.mutate(
      { name: tool.name, patch: { requires_approval: requiresApproval } },
      {
        onSuccess: (t) =>
          toast({
            kind: "ok",
            message: requiresApproval
              ? `Every call to ${t.title} now waits for approval.`
              : `${t.title} now runs without approval.`,
          }),
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't update ${tool.title}. Try again.`) }),
      },
    );
  }

  function confirmDelete() {
    const t = deleting;
    setDeleting(null);
    if (!t) return;
    remove.mutate(t.name, {
      onSuccess: () => toast({ kind: "ok", message: `${t.title} deleted.` }),
      onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't delete ${t.title}. Try again.`) }),
    });
  }

  return (
    <>
      <SectionHeader
        title="Tools"
        description={description}
        actions={
          canEdit && (
            <Button onClick={() => setEditing(null)}>
              <Plus aria-hidden />
              New tool
            </Button>
          )
        }
      />

      {isLoading ? (
        <LoadingRow label="Loading tools…" />
      ) : error ? (
        <ErrorPanel title="Couldn't load tools" error={error} onRetry={() => void refetch()} />
      ) : !tools || tools.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="No tools registered"
          description="The backend didn't report any tools. Check its logs; engineers can also add a custom CLI tool."
        />
      ) : (
        <div className="space-y-8">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative w-full sm:w-72">
              <Search
                aria-hidden
                className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]"
              />
              <label htmlFor="tool-search" className="sr-only">
                Search tools
              </label>
              <input
                id="tool-search"
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search tools…"
                className={cn(inputClass, "pl-9")}
              />
            </div>
            <p className="text-sm text-[var(--muted-foreground)]">
              {inChatCount} of {tools.length} tools available in chat
            </p>
          </div>

          {groups.length === 0 && (
            <EmptyState
              icon={SearchX}
              title="No matching tools"
              description={`Nothing matches “${query.trim()}”. Try another word, or clear the search.`}
            >
              <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                Clear search
              </Button>
            </EmptyState>
          )}

          {groups.map((g) => (
            <section key={g.id} aria-labelledby={`tools-${g.id}`}>
              <h3 id={`tools-${g.id}`} className="mb-3 flex items-center gap-2 text-sm font-semibold">
                <g.icon aria-hidden className="size-4 text-[var(--muted-foreground)]" />
                {g.label}
                <span className="font-normal text-[var(--muted-foreground)]">({g.tools.length})</span>
              </h3>
              {g.id === "custom" && (
                <p className="mb-3 flex items-start gap-2 rounded-md border bg-[var(--muted)]/50 px-3 py-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  A command-line tool the assistant can use, like kubectl-ai&apos;s custom tools. It writes only the
                  arguments; read-only subcommands run at once in the sandbox, anything else waits for an
                  engineer&apos;s approval.
                </p>
              )}
              {g.id === "mcp" && (
                <p className="mb-3 flex items-start gap-2 rounded-md border bg-[var(--muted)]/50 px-3 py-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  Tools from connected MCP servers start disabled, and every call waits for approval. An engineer
                  decides per tool: enable it, and let it run without approval only if it can&apos;t change anything
                  that matters — the server&apos;s own &quot;read-only&quot; claim is shown but not trusted.
                </p>
              )}
              {g.tools.length === 0 ? (
                <EmptyState
                  icon={Terminal}
                  title="No custom tools yet"
                  description="Start from the kubectl or helm template, or wrap any CLI installed in the sandbox."
                >
                  <Button variant="outline" size="sm" onClick={() => setEditing(null)}>
                    <Plus aria-hidden />
                    New tool
                  </Button>
                </EmptyState>
              ) : (
                <ul className="divide-y rounded-lg border">
                  {g.tools.map((t) => (
                    <ToolRow
                      key={t.name}
                      tool={t}
                      canEdit={canEdit}
                      pending={update.isPending && update.variables?.name === t.name}
                      onToggle={(enabled) => toggle(t, enabled)}
                      onTry={() => setTrying(t)}
                      onApproval={
                        t.mcp
                          ? (v) => (v ? setApproval(t, true) : setUnguarding(t))
                          : undefined
                      }
                      onEdit={t.custom ? () => setEditing(t.custom) : undefined}
                      onDelete={t.custom ? () => setDeleting(t) : undefined}
                    />
                  ))}
                </ul>
              )}
            </section>
          ))}
        </div>
      )}

      <ToolTryDialog tool={trying} onClose={() => setTrying(null)} />
      <CustomToolDialog
        open={editing !== undefined}
        editing={editing ?? null}
        takenNames={(tools ?? []).map((t) => t.name)}
        onClose={() => setEditing(undefined)}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={`Delete ${deleting?.title ?? "this tool"}?`}
        description="The assistant can no longer use it. Its past runs and approvals stay in the history. This can't be undone."
        confirmLabel="Delete tool"
        destructive
        onConfirm={confirmDelete}
        onCancel={() => setDeleting(null)}
      />
      <ConfirmDialog
        open={unguarding !== null}
        title={`Let ${unguarding?.title ?? "this tool"} run without approval?`}
        description="The assistant will call it directly, with arguments it writes itself, and nobody reviews the call first. Do this only for tools that can't change anything important."
        confirmLabel="Run without approval"
        destructive
        onConfirm={() => {
          const t = unguarding;
          setUnguarding(null);
          if (t) setApproval(t, false);
        }}
        onCancel={() => setUnguarding(null)}
      />
    </>
  );
}

function StatusBadge({ tool }: { tool: Tool }) {
  if (tool.in_chat) return <Badge tone="success">In chat</Badge>;
  if (!tool.enabled) return <Badge tone="neutral">Disabled</Badge>;
  return <Badge tone="warning">Unavailable</Badge>;
}

function ToolRow({
  tool,
  canEdit,
  pending,
  onToggle,
  onTry,
  onApproval,
  onEdit,
  onDelete,
}: {
  tool: Tool;
  canEdit: boolean;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
  onTry: () => void;
  onApproval?: (requiresApproval: boolean) => void;
  onEdit?: () => void;
  onDelete?: () => void;
}) {
  return (
    <li className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="text-sm font-medium">{tool.title}</p>
          <code className="break-all text-xs text-[var(--muted-foreground)]">{tool.name}</code>
        </div>
        <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">
          {tool.custom ? tool.custom.description : tool.description}
        </p>
        {tool.custom && tool.custom.read_only_prefixes.length > 0 && (
          <p className="mt-1.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
            Runs at once:{" "}
            {tool.custom.read_only_prefixes.map((p) => (
              <code key={p} className="mr-1 inline-block rounded bg-[var(--muted)] px-1 py-0.5">
                {p}
              </code>
            ))}
          </p>
        )}
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {tool.mcp ? (
            tool.mcp.requires_approval ? (
              <Badge tone="warning">
                <PenLine aria-hidden className="size-3" />
                Needs approval
              </Badge>
            ) : (
              <Badge tone="info">Runs directly</Badge>
            )
          ) : (
            <DangerBadge danger={tool.danger} />
          )}
          <Badge tone={tool.custom ? "info" : "neutral"}>{sourceLabel(tool)}</Badge>
          <StatusBadge tool={tool} />
        </div>
        {tool.mcp && (
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">{hintText(tool.mcp.read_only_hint)}</p>
        )}
        {!tool.in_chat && tool.enabled && tool.unavailable_reason && (
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
            <span className="font-medium text-[var(--foreground)]">Unavailable:</span> {tool.unavailable_reason}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {tool.in_chat && (
          <Button variant="outline" size="sm" onClick={onTry}>
            <Play aria-hidden />
            Try it
          </Button>
        )}
        {canEdit && onApproval && tool.mcp && (
          // Boxed, label first: next to the row's Enable switch, a bare
          // "Requires approval" between two switches read as either one's.
          <label className="flex min-h-8 items-center gap-2 rounded-md border px-2 text-xs text-[var(--muted-foreground)]">
            Requires approval
            <Switch
              checked={tool.mcp.requires_approval}
              pending={pending}
              onCheckedChange={onApproval}
              aria-label={`Require approval for each call to ${tool.title}`}
            />
          </label>
        )}
        {canEdit && onEdit && (
          <Button variant="ghost" size="icon" aria-label={`Edit ${tool.title}`} onClick={onEdit}>
            <Pencil aria-hidden />
          </Button>
        )}
        {canEdit && onDelete && (
          <Button variant="ghost" size="icon" aria-label={`Delete ${tool.title}`} onClick={onDelete}>
            <Trash2 aria-hidden />
          </Button>
        )}
        {canEdit && (
          <Switch
            checked={tool.enabled}
            pending={pending}
            onCheckedChange={onToggle}
            aria-label={`${tool.enabled ? "Disable" : "Enable"} ${tool.title}`}
          />
        )}
      </div>
    </li>
  );
}
