"use client";

import { useMemo } from "react";

import { CATEGORY } from "@/components/rca/shared";
import { cn } from "@/lib/utils";
import type { EventCategory, RcaEdge, RcaEvent } from "@/types/rca";

const NODE_W = 208;
const NODE_H = 58;
const COL_GAP = 76;
const ROW_GAP = 18;
const PAD = 12;

// Accent bar per category — the same hues as the category badges.
const BAR: Record<EventCategory, string> = {
  change: "fill-violet-500",
  resource: "fill-amber-500",
  state: "fill-sky-500",
  symptom: "fill-[var(--destructive)]",
  dependency: "fill-[var(--muted-foreground)]",
};

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

interface Placed {
  event: RcaEvent;
  x: number;
  y: number;
}

/**
 * Columns by causal depth: an event sits one column right of its latest cause,
 * so root causes are on the left and symptoms on the right — reading order is
 * cause → effect. Within a column, earlier events first.
 */
function layout(events: RcaEvent[], edges: RcaEdge[]) {
  const ids = new Set(events.map((e) => e.id));
  const live = edges.filter((e) => ids.has(e.cause) && ids.has(e.effect));
  const depth = new Map(events.map((e) => [e.id, 0]));
  // Longest-path relaxation; capped so a cycle (A→B→A) can't loop forever.
  for (let i = 0; i < events.length; i++) {
    let changed = false;
    for (const e of live) {
      const d = depth.get(e.cause)! + 1;
      if (d > depth.get(e.effect)! && d < events.length) {
        depth.set(e.effect, d);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const columns = new Map<number, RcaEvent[]>();
  for (const ev of events) {
    const d = depth.get(ev.id)!;
    columns.set(d, [...(columns.get(d) ?? []), ev]);
  }
  const placed = new Map<string, Placed>();
  let rows = 0;
  for (const [d, col] of [...columns.entries()].sort((a, b) => a[0] - b[0])) {
    col.sort((a, b) => a.start.localeCompare(b.start));
    rows = Math.max(rows, col.length);
    col.forEach((ev, i) => {
      placed.set(ev.id, { event: ev, x: PAD + d * (NODE_W + COL_GAP), y: PAD + i * (NODE_H + ROW_GAP) });
    });
  }
  const width = PAD * 2 + columns.size * NODE_W + Math.max(0, columns.size - 1) * COL_GAP;
  const height = PAD * 2 + rows * NODE_H + Math.max(0, rows - 1) * ROW_GAP;
  return { placed, edges: live, width, height };
}

export function CausalGraph({
  events,
  edges,
  ranks,
  selected,
  onSelect,
}: {
  events: RcaEvent[];
  edges: RcaEdge[];
  /** event id → hypothesis rank, for the "#1" markers. */
  ranks: Map<string, number>;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { placed, edges: live, width, height } = useMemo(() => layout(events, edges), [events, edges]);

  return (
    <div className="overflow-x-auto rounded-lg border bg-[var(--card)]">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Causal graph: ${events.length} events, ${live.length} causal links. Causes on the left, symptoms on the right.`}
        className="block"
      >
        <defs>
          <marker id="rca-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" className="fill-[var(--muted-foreground)]" />
          </marker>
        </defs>

        {live.map((e) => {
          const a = placed.get(e.cause)!;
          const b = placed.get(e.effect)!;
          const x1 = a.x + NODE_W;
          const y1 = a.y + NODE_H / 2;
          const x2 = b.x;
          const y2 = b.y + NODE_H / 2;
          // Same column (a cycle or same depth): loop around the right side.
          const path =
            x2 > x1
              ? `M${x1},${y1} C${x1 + COL_GAP / 2},${y1} ${x2 - COL_GAP / 2},${y2} ${x2 - 2},${y2}`
              : `M${x1},${y1} C${x1 + 40},${y1} ${x1 + 40},${y2} ${b.x + NODE_W + 2},${y2}`;
          const active = selected === e.cause || selected === e.effect;
          return (
            <path
              key={`${e.cause}→${e.effect}`}
              d={path}
              fill="none"
              markerEnd="url(#rca-arrow)"
              strokeWidth={1 + e.weight * 2}
              className={cn(
                active ? "stroke-[var(--foreground)]" : "stroke-[var(--muted-foreground)]",
                active ? "opacity-90" : "opacity-50",
              )}
            >
              <title>{`${e.rule} (weight ${e.weight.toFixed(2)}): ${e.why}`}</title>
            </path>
          );
        })}

        {[...placed.values()].map(({ event, x, y }) => {
          const rank = ranks.get(event.id);
          const isSelected = selected === event.id;
          const label = `${event.title}: ${event.summary}${rank ? `. Root-cause candidate #${rank}` : ""}`;
          return (
            <g
              key={event.id}
              role="button"
              tabIndex={0}
              aria-label={label}
              aria-pressed={isSelected}
              onClick={() => onSelect(event.id)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(event.id);
                }
              }}
              className="group cursor-pointer outline-none"
            >
              <rect
                x={x}
                y={y}
                width={NODE_W}
                height={NODE_H}
                rx={8}
                className={cn(
                  "fill-[var(--background)] stroke-[var(--border)] transition-[stroke] motion-reduce:transition-none",
                  "group-hover:stroke-[var(--muted-foreground)] group-focus-visible:stroke-[var(--ring)]",
                  isSelected && "stroke-[var(--foreground)]",
                )}
                strokeWidth={isSelected ? 2 : 1}
              />
              <rect x={x} y={y} width={5} height={NODE_H} rx={2} className={BAR[event.category]} />
              <text x={x + 14} y={y + 22} className="fill-[var(--foreground)] text-[12px] font-semibold">
                {clip(event.title, 27)}
              </text>
              <text x={x + 14} y={y + 41} className="fill-[var(--muted-foreground)] text-[11px]">
                {clip(`${event.entity.sub || event.entity.kind} ${event.entity.name}`, 30)}
              </text>
              {rank !== undefined && (
                <g>
                  <rect x={x + NODE_W - 34} y={y + 8} width={26} height={18} rx={9} className="fill-[var(--primary)]" />
                  <text
                    x={x + NODE_W - 21}
                    y={y + 21}
                    textAnchor="middle"
                    className="fill-[var(--primary-foreground)] text-[11px] font-semibold"
                  >
                    #{rank}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

export function GraphLegend() {
  return (
    <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--muted-foreground)]" aria-label="Legend">
      {(Object.keys(CATEGORY) as EventCategory[]).map((c) => (
        <li key={c} className="flex items-center gap-1.5">
          <svg aria-hidden width="10" height="10">
            <rect width="10" height="10" rx="2" className={BAR[c]} />
          </svg>
          {CATEGORY[c].label}
        </li>
      ))}
      <li>Thicker arrow = stronger rule. Hover an arrow to see why it links two events.</li>
    </ul>
  );
}
