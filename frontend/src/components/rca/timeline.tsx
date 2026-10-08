"use client";

import { useState } from "react";

import { CATEGORY, clock, entityLabel } from "@/components/rca/shared";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { RcaEvent } from "@/types/rca";

/** Every detected event in time order. Changes made by people stand out: they are the usual cause. */
export function Timeline({
  events,
  selected,
  onSelect,
}: {
  events: RcaEvent[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [onlyGraph, setOnlyGraph] = useState(false);
  const shown = [...events]
    .filter((e) => !onlyGraph || e.in_graph)
    .sort((a, b) => a.start.localeCompare(b.start));
  const hidden = events.filter((e) => !e.in_graph).length;

  return (
    <div>
      {hidden > 0 && (
        <div className="mb-3 flex items-center gap-3">
          <Switch id="rca-only-graph" checked={onlyGraph} onCheckedChange={setOnlyGraph} />
          <label htmlFor="rca-only-graph" className="text-sm">
            Only events in the causal graph{" "}
            <span className="text-[var(--muted-foreground)]">({hidden} others not linked to a symptom)</span>
          </label>
        </div>
      )}
      <ol className="relative space-y-1 border-l pl-4">
        {shown.map((ev) => {
          const cat = CATEGORY[ev.category];
          const Icon = cat.icon;
          return (
            <li key={ev.id} className="relative">
              <span
                aria-hidden
                className={cn(
                  "absolute -left-[21px] top-3 size-2.5 rounded-full border-2 border-[var(--background)]",
                  ev.category === "change" ? "bg-violet-500" : ev.in_graph ? "bg-[var(--foreground)]" : "bg-[var(--border)]",
                )}
              />
              <button
                type="button"
                onClick={() => onSelect(ev.id)}
                aria-pressed={selected === ev.id}
                className={cn(
                  "flex w-full items-start gap-3 rounded-md px-2 py-2 text-left outline-none transition motion-reduce:transition-none",
                  "hover:bg-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                  selected === ev.id && "bg-[var(--accent)]",
                  ev.category === "change" && "bg-violet-500/5",
                  !ev.in_graph && "opacity-70",
                )}
              >
                <span className="w-16 shrink-0 pt-0.5 font-mono text-xs text-[var(--muted-foreground)]">
                  {clock(ev.start)}
                </span>
                <Icon aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)]" />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-medium">{ev.title}</span>
                    {ev.category === "change" && <Badge tone="violet">Change</Badge>}
                  </span>
                  <span className="block text-sm text-[var(--muted-foreground)]">
                    {entityLabel(ev.entity)} — {ev.summary}
                  </span>
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
