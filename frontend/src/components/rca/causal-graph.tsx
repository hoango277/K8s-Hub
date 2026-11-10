"use client";

import { useEffect, useMemo, useRef } from "react";

import { CATEGORY } from "@/components/rca/shared";
import { cn } from "@/lib/utils";
import type { EventCategory, RcaEdge, RcaEvent } from "@/types/rca";

const NODE_W = 200;
const NODE_H = 54;
const COL_GAP = 16;
const ROW_GAP = 44;
const PAD = 12;

// Accent bar per category — the same hues as the category badges.
const BAR: Record<EventCategory, string> = Object.fromEntries(
  Object.entries(CATEGORY).map(([c, v]) => [c, v.bar]),
) as Record<EventCategory, string>;

function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

interface Placed {
  event: RcaEvent;
  x: number;
  y: number;
}

/**
 * Rows by causal depth: an event sits one row below its latest cause, so root
 * causes are on top and symptoms at the bottom — the same reading order as the
 * chain in each cause card. Top-down because the graph shares the page with the
 * cause list: chains are long and narrow, a left-to-right layout overflowed the
 * column. Within a row, events sit under their causes (mean position), then by time.
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
  const layers = new Map<number, RcaEvent[]>();
  for (const ev of events) {
    const d = depth.get(ev.id)!;
    layers.set(d, [...(layers.get(d) ?? []), ev]);
  }
  const ordered = [...layers.entries()].sort((a, b) => a[0] - b[0]).map(([, row]) => row);
  const widest = Math.max(1, ...ordered.map((row) => row.length));
  const width = PAD * 2 + widest * NODE_W + (widest - 1) * COL_GAP;
  const placed = new Map<string, Placed>();
  const slot = new Map<string, number>(); // index within its row, for the next row's ordering
  ordered.forEach((row, r) => {
    const parents = (id: string) => live.filter((e) => e.effect === id && slot.has(e.cause)).map((e) => slot.get(e.cause)!);
    const pos = (id: string) => {
      const p = parents(id);
      return p.length ? p.reduce((s, v) => s + v, 0) / p.length : Number.POSITIVE_INFINITY;
    };
    row.sort((a, b) => pos(a.id) - pos(b.id) || a.start.localeCompare(b.start));
    const rowWidth = row.length * NODE_W + (row.length - 1) * COL_GAP;
    const left = (width - rowWidth) / 2;
    row.forEach((ev, i) => {
      slot.set(ev.id, i + (widest - row.length) / 2); // centred rows: compare on the same scale
      placed.set(ev.id, { event: ev, x: left + i * (NODE_W + COL_GAP), y: PAD + r * (NODE_H + ROW_GAP) });
    });
  });
  const height = PAD * 2 + ordered.length * NODE_H + Math.max(0, ordered.length - 1) * ROW_GAP;
  return { placed, edges: live, width, height };
}

export function CausalGraph({
  events,
  edges,
  ranks,
  path,
  selected,
  onSelect,
}: {
  events: RcaEvent[];
  edges: RcaEdge[];
  /** event id → hypothesis rank, for the "#1" markers. */
  ranks: Map<string, number>;
  /** The focused cause's chain, root first: every link on it is highlighted, the rest dimmed. */
  path: string[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { placed, edges: live, width, height } = useMemo(() => layout(events, edges), [events, edges]);
  const box = useRef<HTMLDivElement>(null);
  const onPath = useMemo(() => new Set(path), [path]);
  const pathLinks = useMemo(() => new Set(path.slice(1).map((id, i) => `${path[i]}→${id}`)), [path]);

  // A very wide row still scrolls sideways: bring the focused root to the middle,
  // so "focus a cause" never needs a hunt across the graph.
  const root = path[0];
  useEffect(() => {
    const el = box.current;
    const node = root ? placed.get(root) : undefined;
    if (!el || !node || el.scrollWidth <= el.clientWidth) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ left: Math.max(0, node.x + NODE_W / 2 - el.clientWidth / 2), behavior: reduce ? "auto" : "smooth" });
  }, [root, placed]);

  return (
    <div ref={box} className="overflow-x-auto rounded-lg border bg-[var(--card)]">
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="group"
        aria-label={`Causal graph: ${events.length} events, ${live.length} causal links. Causes on top, symptoms below.`}
        className="mx-auto block"
      >
        <defs>
          <marker id="rca-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" className="fill-[var(--muted-foreground)]" />
          </marker>
          <marker id="rca-arrow-on" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" className="fill-[var(--brand)]" />
          </marker>
        </defs>

        {live.filter((e) => !isActive(e)).map(edge)}

        {[...placed.values()].map(({ event, x, y }) => {
          const rank = ranks.get(event.id);
          const isSelected = selected === event.id;
          const dimmed = onPath.size > 0 && !onPath.has(event.id) && !isSelected;
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
              className={cn(
                "group cursor-pointer outline-none transition-opacity motion-reduce:transition-none",
                dimmed && "opacity-40 hover:opacity-100",
              )}
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
                  onPath.has(event.id) && "stroke-[var(--brand)]",
                  isSelected && "stroke-[var(--foreground)]",
                )}
                strokeWidth={isSelected ? 2.5 : onPath.has(event.id) ? 2 : 1}
              />
              <rect x={x} y={y} width={5} height={NODE_H} rx={2} className={BAR[event.category]} />
              <text x={x + 14} y={y + 22} className="fill-[var(--foreground)] text-[12px] font-semibold">
                {clip(event.title, 24)}
              </text>
              <text x={x + 14} y={y + 40} className="fill-[var(--muted-foreground)] text-[11px]">
                {clip(`${event.entity.sub || event.entity.kind} ${event.entity.name}`, 29)}
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

        {/* The highlighted path goes over the nodes, so a link that skips a row stays readable. */}
        {live.filter(isActive).map(edge)}
      </svg>
    </div>
  );

  function isActive(e: RcaEdge): boolean {
    if (pathLinks.size) return pathLinks.has(`${e.cause}→${e.effect}`);
    return selected === e.cause || selected === e.effect;
  }

  function edge(e: RcaEdge) {
    const a = placed.get(e.cause)!;
    const b = placed.get(e.effect)!;
    const x1 = a.x + NODE_W / 2;
    const y1 = a.y + NODE_H;
    const x2 = b.x + NODE_W / 2;
    const y2 = b.y;
    // Same row or upwards (a cycle): loop around the right side.
    const d =
      y2 > y1
        ? `M${x1},${y1} C${x1},${y1 + ROW_GAP / 2} ${x2},${y2 - ROW_GAP / 2} ${x2},${y2 - 2}`
        : `M${a.x + NODE_W},${a.y + NODE_H / 2} C${a.x + NODE_W + 40},${a.y + NODE_H / 2} ${b.x + NODE_W + 40},${b.y + NODE_H / 2} ${b.x + NODE_W + 2},${b.y + NODE_H / 2}`;
    const active = isActive(e);
    return (
      <path
        key={`${e.cause}→${e.effect}`}
        d={d}
        fill="none"
        markerEnd={active ? "url(#rca-arrow-on)" : "url(#rca-arrow)"}
        strokeWidth={active ? 2.5 + e.weight * 1.5 : 1 + e.weight * 2}
        className={cn(
          "transition-opacity motion-reduce:transition-none",
          active ? "stroke-[var(--brand)] opacity-100" : "stroke-[var(--muted-foreground)]",
          !active && (pathLinks.size ? "opacity-20" : "opacity-50"),
        )}
      >
        <title>{`${e.rule} (weight ${e.weight.toFixed(2)}): ${e.why}`}</title>
      </path>
    );
  }
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
      <li>Highlighted: the selected cause&apos;s path. Hover an arrow for its rule.</li>
    </ul>
  );
}
