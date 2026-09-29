"use client";

import { useMemo, useState } from "react";
import {
  Activity,
  Boxes,
  Eye,
  Info,
  PenLine,
  Play,
  Plug,
  ScrollText,
  Search,
  SearchX,
  TriangleAlert,
  Waypoints,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { ErrorPanel, LoadingRow, SectionHeader, errorMessage } from "@/components/skills/shared";
import { ToolTryDialog } from "@/components/skills/tool-try-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { inputClass } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useTools, useUpdateTool } from "@/hooks/use-tools";
import { cn } from "@/lib/utils";
import type { Tool, ToolCategory, ToolDanger } from "@/types/tool";

const CATEGORIES: { id: ToolCategory; label: string; icon: LucideIcon }[] = [
  { id: "kubernetes", label: "Kubernetes", icon: Boxes },
  { id: "metrics", label: "Metrics", icon: Activity },
  { id: "logs", label: "Logs", icon: ScrollText },
  { id: "traces", label: "Traces", icon: Waypoints },
  { id: "external", label: "External (MCP)", icon: Plug },
];

export const DANGER: Record<
  ToolDanger,
  { label: string; tone: "success" | "warning" | "danger"; icon: LucideIcon; description: string }
> = {
  read: {
    label: "Read",
    tone: "success",
    icon: Eye,
    description: "Only reads data. Can be used in chat.",
  },
  write: {
    label: "Write",
    tone: "warning",
    icon: PenLine,
    description: "Changes something. Kept out of chat until approvals exist.",
  },
  destructive: {
    label: "Destructive",
    tone: "danger",
    icon: TriangleAlert,
    description: "Deletes or breaks things. Kept out of chat.",
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

function isMcp(tool: Tool): boolean {
  return tool.source.startsWith("mcp:");
}

function sourceLabel(tool: Tool): string {
  return isMcp(tool) ? `MCP · ${tool.source.slice(4)}` : "Built-in";
}

export function ToolsPanel({ canEdit, description }: { canEdit: boolean; description: string }) {
  const { data: tools, isLoading, error, refetch } = useTools();
  const update = useUpdateTool();
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [trying, setTrying] = useState<Tool | null>(null);

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
      (g) => g.tools.length > 0,
    );
  }, [tools, query]);

  const inChatCount = (tools ?? []).filter((t) => t.in_chat).length;

  function patch(tool: Tool, change: { enabled?: boolean; danger?: ToolDanger }) {
    update.mutate(
      { name: tool.name, patch: change },
      {
        onSuccess: (t) => {
          const message =
            change.enabled !== undefined
              ? t.in_chat
                ? `${t.title} is enabled and available in chat.`
                : change.enabled
                  ? `${t.title} is enabled${t.unavailable_reason ? `, but can't run yet: ${t.unavailable_reason}` : "."}`
                  : `${t.title} is disabled.`
              : `${t.title} is now marked ${DANGER[t.danger].label}.${t.in_chat ? " It's available in chat." : ""}`;
          toast({ kind: "ok", message });
        },
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't update ${tool.title}. Try again.`) }),
      },
    );
  }

  return (
    <>
      <SectionHeader title="Tools" description={description} />

      {isLoading ? (
        <LoadingRow label="Loading tools…" />
      ) : error ? (
        <ErrorPanel title="Couldn't load tools" error={error} onRetry={() => void refetch()} />
      ) : !tools || tools.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title="No tools registered"
          description="The backend didn't report any tools. Check its logs, or connect an MCP server to add external tools."
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
              {g.id === "external" && (
                <p className="mb-3 flex items-start gap-2 rounded-md border bg-[var(--muted)]/50 px-3 py-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
                  <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
                  New MCP tools start disabled and marked Write. An engineer reviews each one, marks it Read if it
                  only reads data, and enables it — only then can the assistant use it.
                </p>
              )}
              <ul className="divide-y rounded-lg border">
                {g.tools.map((t) => (
                  <ToolRow
                    key={t.name}
                    tool={t}
                    canEdit={canEdit}
                    pending={update.isPending && update.variables?.name === t.name}
                    onPatch={(change) => patch(t, change)}
                    onTry={() => setTrying(t)}
                  />
                ))}
              </ul>
            </section>
          ))}
        </div>
      )}

      <ToolTryDialog tool={trying} onClose={() => setTrying(null)} />
    </>
  );
}

function StatusBadge({ tool }: { tool: Tool }) {
  if (tool.in_chat) return <Badge tone="success">In chat</Badge>;
  if (!tool.enabled) return <Badge tone="neutral">Disabled</Badge>;
  return <Badge tone="warning">Unavailable</Badge>;
}

function hintText(hint: boolean | null): string {
  if (hint === true) return "The server says this tool only reads. Check the description before trusting that.";
  if (hint === false) return "The server says this tool can make changes.";
  return "The server doesn't say whether this tool changes anything.";
}

function ToolRow({
  tool,
  canEdit,
  pending,
  onPatch,
  onTry,
}: {
  tool: Tool;
  canEdit: boolean;
  pending: boolean;
  onPatch: (change: { enabled?: boolean; danger?: ToolDanger }) => void;
  onTry: () => void;
}) {
  const mcp = isMcp(tool);
  const dangerId = `danger-${tool.name}`;

  return (
    <li className="grid gap-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="text-sm font-medium">{tool.title}</p>
          <code className="break-all text-xs text-[var(--muted-foreground)]">{tool.name}</code>
        </div>
        <p className="mt-1 text-sm leading-relaxed text-[var(--muted-foreground)]">{tool.description}</p>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <DangerBadge danger={tool.danger} />
          <Badge tone={mcp ? "info" : "neutral"}>{sourceLabel(tool)}</Badge>
          <StatusBadge tool={tool} />
        </div>
        {!tool.in_chat && tool.enabled && tool.unavailable_reason && (
          <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
            <span className="font-medium text-[var(--foreground)]">Unavailable:</span> {tool.unavailable_reason}
          </p>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-3 sm:justify-end">
        {canEdit && mcp && (
          <div className="w-full space-y-1 sm:w-56">
            <label htmlFor={dangerId} className="sr-only">
              Danger level for {tool.title}
            </label>
            <Select
              value={tool.danger}
              onValueChange={(v) => onPatch({ danger: v as ToolDanger })}
              disabled={pending}
            >
              <SelectTrigger id={dangerId} className="h-8 w-full justify-between rounded-md">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(DANGER) as ToolDanger[]).map((d) => (
                  <SelectItem key={d} value={d} description={DANGER[d].description}>
                    {DANGER[d].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] leading-snug text-[var(--muted-foreground)]">{hintText(tool.read_only_hint)}</p>
          </div>
        )}
        {tool.in_chat && (
          <Button variant="outline" size="sm" onClick={onTry}>
            <Play aria-hidden />
            Try it
          </Button>
        )}
        {canEdit && (
          <Switch
            checked={tool.enabled}
            pending={pending}
            onCheckedChange={(enabled) => onPatch({ enabled })}
            aria-label={`${tool.enabled ? "Disable" : "Enable"} ${tool.title}`}
          />
        )}
      </div>
    </li>
  );
}
