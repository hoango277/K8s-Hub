"use client";

import { Wrench } from "lucide-react";

import { FormError } from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useProposeFix } from "@/hooks/use-rca";
import type { RcaFix } from "@/types/rca";

/** A concrete fix computed by the engine (remediation.py). Proposing only creates an approval request. */
export function FixRow({ runId, fix, aiPick }: { runId: string; fix: RcaFix; aiPick: boolean }) {
  const propose = useProposeFix(runId);
  const toast = useToast();
  return (
    <div className="rounded-md border border-[var(--success)]/40 bg-[var(--success)]/5 px-3 py-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <Wrench aria-hidden className="size-4 shrink-0 text-[var(--success)]" />
        <p className="min-w-0 flex-1 text-sm">
          {fix.title}
          {aiPick && (
            <Badge tone="success" className="ml-2 align-middle">
              AI pick
            </Badge>
          )}
        </p>
        <Button
          size="sm"
          variant={aiPick ? "primary" : "outline"}
          title="Creates an approval request with a dry-run diff. Nothing changes until an engineer approves it."
          disabled={propose.isPending}
          onClick={() =>
            propose.mutate(fix.id, {
              onSuccess: () => toast({ kind: "ok", message: "Fix proposed. It's waiting for approval." }),
            })
          }
        >
          {propose.isPending && <Spinner />}
          Propose
        </Button>
      </div>
      {propose.error && (
        <div className="mt-2">
          <FormError error={propose.error} fallback="The fix could not be proposed." />
        </div>
      )}
    </div>
  );
}
