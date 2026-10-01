"use client";

import { useEffect, useState } from "react";

/** Seconds since `startedAt`, ticking once a second while mounted. */
function useElapsed(startedAt: number | null): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (startedAt === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [startedAt]);
  return startedAt === null ? 0 : Math.max(0, Math.floor((now - startedAt) / 1000));
}

/**
 * What the assistant is doing while there is no answer text yet.
 *
 * Covers the gap the activity block can't: after the last tool returned and
 * before the first word arrives, the model is still working (up to a minute
 * with some models) — without this the screen just sat still and looked hung.
 *
 * The label says the phase, the counter says it's alive; after 20 s a hint
 * says that's normal. Skeleton lines stand in for the answer only at the very
 * start, before anything else is on screen. Motion stops with
 * prefers-reduced-motion (see globals.css); the words carry the meaning.
 */
export function WaitingIndicator({
  label,
  startedAt,
  skeleton = false,
}: {
  label: string;
  startedAt: number | null;
  skeleton?: boolean;
}) {
  const seconds = useElapsed(startedAt);

  return (
    <div className="k8s-fade-in space-y-3">
      <div role="status" className="flex items-center gap-2.5 text-xs">
        <span aria-hidden className="k8s-orb shrink-0" />
        <span className="k8s-shimmer font-medium">{label}</span>
        {seconds >= 3 && (
          // Not announced every second to screen readers: aria-hidden on the
          // counter, the label above is what the status region reads out.
          <span aria-hidden className="tabular-nums text-[var(--muted-foreground)]">
            · {seconds}s
          </span>
        )}
        {seconds >= 20 && (
          <span className="hidden text-[var(--muted-foreground)] sm:inline">
            — larger models can take up to a minute
          </span>
        )}
      </div>

      {skeleton && (
        <div aria-hidden className="space-y-2">
          <div className="k8s-skeleton h-3 w-[92%]" />
          <div className="k8s-skeleton h-3 w-[78%]" />
          <div className="k8s-skeleton h-3 w-[55%]" />
        </div>
      )}
    </div>
  );
}
