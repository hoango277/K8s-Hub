"use client";

import { X } from "lucide-react";

import { CATEGORY, clock, entityLabel } from "@/components/rca/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RcaEdge, RcaEvent } from "@/types/rca";

/** Everything known about one event: its evidence and the rules linking it. */
export function EventDetails({
  event,
  events,
  edges,
  onSelect,
  onClose,
}: {
  event: RcaEvent;
  events: Map<string, RcaEvent>;
  edges: RcaEdge[];
  onSelect: (id: string) => void;
  onClose: () => void;
}) {
  const cat = CATEGORY[event.category];
  const causes = edges.filter((e) => e.effect === event.id);
  const effects = edges.filter((e) => e.cause === event.id);
  return (
    <section aria-label={`Details of ${event.title}`} className="rounded-lg border bg-[var(--card)] p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="font-semibold">{event.title}</h3>
            <Badge tone={cat.tone}>{cat.label}</Badge>
          </div>
          <p className="mt-1 text-sm">{event.summary}</p>
          <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
            {entityLabel(event.entity)} · since {clock(event.start)}
          </p>
        </div>
        <Button variant="ghost" size="icon" aria-label="Close details" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>

      <h4 className="mt-4 text-xs font-medium text-[var(--muted-foreground)]">Evidence</h4>
      {event.evidence.length === 0 ? (
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">No quote was kept for this event.</p>
      ) : (
        <ul className="mt-1 space-y-1.5">
          {event.evidence.map((ev) => (
            <li key={ev.id} className="rounded-md bg-[var(--muted)] px-3 py-2 text-sm">
              <p className="break-words">{ev.text}</p>
              <p className="mt-0.5 font-mono text-[11px] text-[var(--muted-foreground)]">
                {ev.source}
                {ev.at ? ` · ${clock(ev.at)}` : ""} · {ev.id}
              </p>
            </li>
          ))}
        </ul>
      )}

      {[
        { title: "Caused by", list: causes, other: (e: RcaEdge) => e.cause },
        { title: "Leads to", list: effects, other: (e: RcaEdge) => e.effect },
      ].map(
        ({ title, list, other }) =>
          list.length > 0 && (
            <div key={title}>
              <h4 className="mt-4 text-xs font-medium text-[var(--muted-foreground)]">{title}</h4>
              <ul className="mt-1 space-y-1">
                {list.map((e) => {
                  const ev = events.get(other(e));
                  return (
                    <li key={other(e)} className="text-sm">
                      <button
                        type="button"
                        onClick={() => onSelect(other(e))}
                        className="rounded-sm text-left font-medium underline-offset-2 outline-none hover:underline focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
                      >
                        {ev ? `${ev.title} — ${entityLabel(ev.entity)}` : other(e)}
                      </button>
                      <span className="text-[var(--muted-foreground)]"> · {e.why}</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          ),
      )}
    </section>
  );
}
