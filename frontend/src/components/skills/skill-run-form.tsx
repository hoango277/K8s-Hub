"use client";

import { useState } from "react";
import { CircleCheck, CircleX, Play, Terminal } from "lucide-react";

import { FormError, OutputBlock, SCRIPT_ARGS_MAX, formatDuration, splitArgs } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { inputClass } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useRunSkillScript } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";

/** Run one of a skill's scripts by hand, on the backend, and show the result. */
export function SkillRunForm({ skill, script }: { skill: string; script: string }) {
  const run = useRunSkillScript();
  const toast = useToast();
  const [raw, setRaw] = useState("");
  const { args, error } = splitArgs(raw);
  const id = `run-args-${script}`;
  const busy = run.isPending;
  const result = run.data;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (error) return;
    run.mutate(
      { name: skill, script, args },
      {
        onSuccess: (r) =>
          toast(
            r.ok
              ? { kind: "ok", message: `${script} finished in ${formatDuration(r.duration_ms)}.` }
              : { kind: "error", message: `${script} failed${r.exit_code !== null ? ` with exit code ${r.exit_code}` : ""}.` },
          ),
      },
    );
  }

  return (
    <section aria-labelledby={`${id}-title`} className="rounded-lg border">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Terminal aria-hidden className="size-4 text-[var(--muted-foreground)]" />
        <h3 id={`${id}-title`} className="text-sm font-semibold">
          Run script
        </h3>
      </header>
      <form onSubmit={submit} noValidate className="space-y-3 p-4">
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          Runs <code>{script}</code> on the K8s Hub server — not in the cluster — with a time limit. The run is
          recorded in the history below.
        </p>
        <div className="space-y-1.5">
          <label htmlFor={id} className="text-sm font-medium">
            Arguments <span className="font-normal text-[var(--muted-foreground)]">(optional)</span>
          </label>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              id={id}
              autoComplete="off"
              spellCheck={false}
              className={cn(inputClass, "font-mono")}
              placeholder='--namespace default "my pod"'
              value={raw}
              onChange={(e) => {
                setRaw(e.target.value);
                run.reset();
              }}
              disabled={busy}
              aria-invalid={Boolean(error)}
              aria-describedby={`${id}-description`}
            />
            <Button type="submit" disabled={busy || Boolean(error)}>
              {busy ? <Spinner className="text-current" label="Running" /> : <Play aria-hidden />}
              {busy ? "Running…" : "Run"}
            </Button>
          </div>
          <p
            id={`${id}-description`}
            className={error ? "text-xs text-[var(--destructive)]" : "text-xs text-[var(--muted-foreground)]"}
          >
            {error ??
              `Separated by spaces; wrap an argument in quotes to keep its spaces. Up to ${SCRIPT_ARGS_MAX}. ${
                args.length > 0 ? `${args.length} ${args.length === 1 ? "argument" : "arguments"}.` : ""
              }`}
          </p>
        </div>

        <FormError error={run.error} fallback="Couldn't run the script. Try again." />

        {result && (
          <div className="k8s-fade-in space-y-2" aria-live="polite">
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              {result.ok ? (
                <span className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-400">
                  <CircleCheck aria-hidden className="size-4" /> Succeeded
                </span>
              ) : (
                <span className="flex items-center gap-1.5 font-medium text-[var(--destructive)]">
                  <CircleX aria-hidden className="size-4" /> Failed
                </span>
              )}
              <span className="text-xs text-[var(--muted-foreground)]">
                Exit code <code>{result.exit_code ?? "none"}</code> · {formatDuration(result.duration_ms)}
              </span>
            </p>
            <OutputBlock text={result.output} />
          </div>
        )}
      </form>
    </section>
  );
}
