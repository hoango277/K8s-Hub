"use client";

import { useMemo, useState } from "react";
import { RotateCcw, Settings } from "lucide-react";

import { FieldInput } from "@/components/settings/field-input";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useReloadEnv, useResetSettings, useSettings, useUpdateSettings } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { DANGEROUS_OPTIONS, GROUP_ORDER, groupOf, type SettingField } from "@/types/settings";

/** Value shown for a field: the draft if edited, otherwise the server value. */
type Draft = Record<string, unknown>;

function displayValue(field: SettingField): unknown {
  // The server never returns the value of a secret.
  return field.secret ? "" : field.value;
}

function isEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function SettingsForm() {
  const { data, isLoading, error, refetch } = useSettings();
  const update = useUpdateSettings();
  const resetAll = useResetSettings();
  const reloadEnv = useReloadEnv();

  const [draft, setDraft] = useState<Draft>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const changed = useMemo(() => {
    if (!data) return [] as string[];
    return Object.keys(draft).filter((name) => {
      const field = data.fields.find((f) => f.name === name);
      if (!field) return false;
      // A secret only counts as changed once the user types something.
      if (field.secret) return typeof draft[name] === "string" && draft[name] !== "";
      return !isEqual(draft[name], field.value);
    });
  }, [draft, data]);

  const isSubmitting = update.isPending || resetAll.isPending || reloadEnv.isPending;
  const submitError = update.error instanceof ApiError ? update.error.message : null;

  function setValue(name: string, value: unknown) {
    setDraft((d) => ({ ...d, [name]: value }));
    setNotice(null);
    update.reset();
  }

  function discard() {
    setDraft({});
    setNotice(null);
    update.reset();
  }

  async function save() {
    if (!data || changed.length === 0) return;

    const values: Record<string, unknown> = {};
    for (const name of changed) {
      const field = data.fields.find((f) => f.name === name)!;
      let value = draft[name];

      // JSON fields are typed as text and must be parsed before sending.
      if (field.type === "object" && typeof value === "string") {
        try {
          value = value.trim() === "" ? {} : JSON.parse(value);
        } catch {
          setNotice(`${field.name}: not valid JSON`);
          return;
        }
      }
      values[name] = value;
    }

    try {
      await update.mutateAsync({ values });
      setDraft({});
      setNotice(`Saved ${changed.length} ${changed.length === 1 ? "change" : "changes"}`);
    } catch {
      /* the error is shown via update.error */
    }
  }

  async function restore(field: SettingField) {
    // Sending null makes the backend drop the override and fall back to .env.
    await update.mutateAsync({ values: { [field.name]: null } });
    setDraft((d) => {
      const rest = { ...d };
      delete rest[field.name];
      return rest;
    });
    setNotice(`Restored ${field.name} to its .env value`);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 p-16 text-sm text-[var(--muted-foreground)]">
        <Spinner /> Loading settings…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto max-w-4xl px-6 pt-8">
        <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-5 text-sm">
          <p className="font-medium text-[var(--destructive)]">Couldn&apos;t load settings</p>
          <p className="mt-1 text-[var(--muted-foreground)]">
            {error instanceof Error ? error.message : "Check that the backend is running, then try again."}
          </p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const groups = GROUP_ORDER.map((g) => ({
    name: g,
    fields: data.fields.filter((f) => groupOf(f.name) === g),
  })).filter((g) => g.fields.length > 0);

  return (
    <div className="mx-auto max-w-4xl px-6 pt-8">
      <PageHeader
        icon={Settings}
        title="System settings"
        description={
          <>
            Changes here take effect immediately, no restart needed. The base values live in the{" "}
            <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-xs">.env</code> file.
          </>
        }
      />

      {groups.map((group) => (
        <section key={group.name} className="mb-10">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
            {group.name}
          </h2>

          <div className="divide-y rounded-lg border">
            {group.fields.map((field) => {
              const hasDraft = field.name in draft;
              const value = hasDraft ? draft[field.name] : displayValue(field);
              const isChanged = changed.includes(field.name);
              const showWarning =
                DANGEROUS_OPTIONS[field.name]?.includes(String(value)) ?? false;

              return (
                <div key={field.name} className="grid gap-3 p-4 sm:grid-cols-[1fr_20rem]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="text-sm font-medium">{field.name}</code>
                      {field.overridden && <Badge>Overridden</Badge>}
                      {isChanged && <Badge tone="warning">Unsaved</Badge>}
                    </div>

                    {field.description && (
                      <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
                        {field.description}
                      </p>
                    )}

                    {field.overridden && !field.secret && (
                      <button
                        type="button"
                        onClick={() => void restore(field)}
                        disabled={isSubmitting}
                        className="mt-1.5 text-xs text-[var(--muted-foreground)] underline underline-offset-2 hover:text-[var(--foreground)] disabled:opacity-50"
                      >
                        Restore to {JSON.stringify(field.env_value)}
                      </button>
                    )}

                    {showWarning && (
                      <p className="mt-2 rounded-md bg-[var(--destructive)]/10 px-2 py-1.5 text-xs text-[var(--destructive)]">
                        This mode lets the AI act on the cluster without human approval. Use it on
                        test clusters only.
                      </p>
                    )}
                  </div>

                  <div className="sm:pt-0.5">
                    <FieldInput
                      field={field}
                      value={value}
                      onChange={(v) => setValue(field.name, v)}
                    />
                    {field.secret && field.is_set && (
                      <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                        A key is already set. Leave blank to keep it.
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {/* Action bar sticks to the bottom of the CONTENT AREA — `sticky`, not `fixed`:
          fixed spans the full screen width, so it covers the sidebar and drifts off the content column. */}
      <div className="sticky bottom-0 -mx-6 mt-2 border-t bg-[var(--background)]/95 backdrop-blur">
        <div className="flex flex-wrap items-center gap-3 px-6 py-3">
          <Button onClick={() => void save()} disabled={changed.length === 0 || isSubmitting}>
            {update.isPending ? "Saving…" : `Save changes${changed.length ? ` (${changed.length})` : ""}`}
          </Button>

          <Button variant="outline" onClick={discard} disabled={changed.length === 0 || isSubmitting}>
            Cancel
          </Button>

          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void reloadEnv.mutateAsync().then(() => setNotice("Reloaded the .env file"))}
              disabled={isSubmitting}
              title="Re-read the .env file from disk, keeping the changes made here"
            >
              {reloadEnv.isPending ? <Spinner /> : <RotateCcw aria-hidden />}
              Reload .env
            </Button>

            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmReset(true)}
              disabled={Object.keys(data.overrides).length === 0 || isSubmitting}
              className="text-[var(--destructive)] hover:text-[var(--destructive)]"
            >
              Reset all
            </Button>
          </div>
        </div>

        {(submitError || notice) && (
          <div
            className={cn(
              "border-t px-6 py-2 text-sm",
              submitError
                ? "bg-[var(--destructive)]/10 text-[var(--destructive)]"
                : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
            )}
          >
            <div role={submitError ? "alert" : "status"}>
              {submitError ?? notice}
            </div>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmReset}
        destructive
        title="Reset all settings?"
        description="Every change saved from this page is discarded and the system goes back to the values in the .env file. API keys entered here are removed too."
        confirmLabel="Reset"
        onConfirm={() => {
          setConfirmReset(false);
          void resetAll.mutateAsync().then(() => {
            setDraft({});
            setNotice("Restored the settings from .env");
          });
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}
