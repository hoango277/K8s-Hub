"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";

import { keyLabel } from "@/components/rca/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DependencySource, RcaDependency } from "@/types/rca";

const SOURCE: Record<DependencySource, { label: string; title: string }> = {
  config: { label: "config", title: "A host name in its env or ConfigMaps" },
  metric: { label: "metric", title: "Beyla client metrics in Prometheus" },
  trace: { label: "trace", title: "Spans in Tempo" },
  log: { label: "log", title: "Named in its error logs" },
  annotation: { label: "annotation", title: "The k8s-hub.io/depends-on annotation" },
};
const SHOWN = 8;

/** What the diagnosis looked at: the namespaces, and the "who calls whom" that pulled them in. */
export function Dependencies({
  namespaces,
  dependencies,
}: {
  namespaces: string[];
  dependencies: RcaDependency[];
}) {
  const [all, setAll] = useState(false);
  const cluster = namespaces.includes("*");
  // Calls that leave their namespace first: they are why the scope grew.
  const sorted = [...dependencies].sort(
    (a, b) => Number(crossNs(b)) - Number(crossNs(a)) || a.caller.localeCompare(b.caller),
  );
  const shown = all ? sorted : sorted.slice(0, SHOWN);

  return (
    <div className="rounded-lg border bg-[var(--card)] p-4">
      <p className="text-sm">
        {cluster ? (
          "Every namespace was analysed."
        ) : (
          <>
            Analysed{" "}
            {namespaces.map((n, i) => (
              <span key={n}>
                {i > 0 && ", "}
                <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-xs">{n}</code>
              </span>
            ))}
            {namespaces.length > 1 && " — the namespaces it depends on were pulled in."}
          </>
        )}
      </p>
      {dependencies.length === 0 ? (
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
          No service-to-service calls were found: no host names in configuration, no client metrics, traces or log
          mentions.
        </p>
      ) : (
        <>
          <ul className="mt-3 space-y-1.5" aria-label="Service dependencies">
            {shown.map((d) => (
              <li key={`${d.caller}>${d.callee}`} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                <span className="font-mono text-xs">{keyLabel(d.caller)}</span>
                <ArrowRight aria-label="calls" className="size-3.5 text-[var(--muted-foreground)]" />
                <span className="font-mono text-xs">{keyLabel(d.callee)}</span>
                {d.sources.map((s) => (
                  <Badge key={s} tone={s === "config" || s === "annotation" ? "neutral" : "info"} title={SOURCE[s]?.title}>
                    {SOURCE[s]?.label ?? s}
                  </Badge>
                ))}
              </li>
            ))}
          </ul>
          {sorted.length > SHOWN && (
            <Button variant="ghost" size="sm" className="mt-2" onClick={() => setAll((v) => !v)}>
              {all ? "Show fewer" : `Show all ${sorted.length}`}
            </Button>
          )}
        </>
      )}
    </div>
  );
}

function crossNs(d: RcaDependency): boolean {
  return d.caller.split("/")[1] !== d.callee.split("/")[1];
}
