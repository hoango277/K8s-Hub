"use client";

import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import { CircleAlert, CircleCheck, RotateCcw, Settings, TriangleAlert, Undo2 } from "lucide-react";

import { ApiKeyCard } from "@/components/settings/api-key-card";
import { ConnectionsPanel } from "@/components/settings/connections-panel";
import {
  GenericControl,
  ModeControl,
  ModeWarning,
  NamespaceControl,
  NumberControl,
  SliderControl,
  validate,
} from "@/components/settings/controls";
import { HistoryPanel } from "@/components/settings/history-panel";
import {
  fieldMeta,
  fieldOrder,
  formatValue,
  SECTIONS,
  type FieldMeta,
  type SectionId,
} from "@/components/settings/meta";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { useReloadEnv, useResetSettings, useSettings, useUpdateSettings } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { SettingField } from "@/types/settings";

type Draft = Record<string, unknown>;

interface Toast {
  kind: "ok" | "error";
  message: string;
}

// ---------------------------------------------------------------------------
// The open section lives in the URL hash (#keys, #history…) so it survives a
// reload, can be linked to, and works with the back button. Read through
// useSyncExternalStore: reading `location` during render would mismatch the
// server HTML and break hydration.
// ---------------------------------------------------------------------------

function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function useSectionFromHash(valid: SectionId[]): SectionId {
  const hash = useSyncExternalStore(
    subscribeHash,
    () => window.location.hash.slice(1),
    () => "",
  );
  return valid.includes(hash as SectionId) ? (hash as SectionId) : valid[0];
}

function isEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function SettingsPage() {
  const { data, isLoading, error, refetch } = useSettings();
  const update = useUpdateSettings();
  const resetAll = useResetSettings();
  const reloadEnv = useReloadEnv();

  const [draft, setDraft] = useState<Draft>({});
  const [toast, setToast] = useState<Toast | null>(null);
  const [confirmReset, setConfirmReset] = useState(false);

  const busy = update.isPending || resetAll.isPending || reloadEnv.isPending;

  const fields = useMemo(() => data?.fields ?? [], [data]);
  const byName = useMemo(() => new Map(fields.map((f) => [f.name, f])), [fields]);

  // "Other" only appears when the backend has a field this page doesn't know yet.
  const sections = useMemo(
    () => SECTIONS.filter((s) => s.id !== "other" || fields.some((f) => fieldMeta(f.name, f.type).section === "other")),
    [fields],
  );
  const current = useSectionFromHash(sections.map((s) => s.id));
  const section = sections.find((s) => s.id === current)!;

  const changed = useMemo(
    () =>
      Object.keys(draft).filter((name) => {
        const field = byName.get(name);
        if (!field) return false;
        // A key only counts once something is typed.
        if (field.secret) return typeof draft[name] === "string" && draft[name] !== "";
        return !isEqual(draft[name], field.value);
      }),
    [draft, byName],
  );
  const errors = useMemo(() => {
    const out: Record<string, string> = {};
    for (const name of changed) {
      const msg = validate(byName.get(name)!, draft[name]);
      if (msg) out[name] = msg;
    }
    return out;
  }, [changed, draft, byName]);
  const hasErrors = Object.keys(errors).length > 0;

  const dirtySections = useMemo(
    () => new Set(changed.map((n) => fieldMeta(n, byName.get(n)!.type).section)),
    [changed, byName],
  );

  // Closing or reloading the tab with unsaved edits asks first.
  useEffect(() => {
    if (changed.length === 0) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [changed.length]);

  // Success toasts dismiss themselves; errors stay until the next action.
  useEffect(() => {
    if (toast?.kind !== "ok") return;
    const t = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(t);
  }, [toast]);

  function setValue(name: string, value: unknown) {
    setDraft((d) => {
      const next = { ...d };
      if (value === undefined) delete next[name];
      else next[name] = value;
      return next;
    });
    update.reset();
  }

  async function save() {
    if (changed.length === 0 || hasErrors) return;
    const values = Object.fromEntries(changed.map((n) => [n, draft[n]]));
    try {
      await update.mutateAsync({ values });
      setDraft({});
      setToast({ kind: "ok", message: `Saved ${changed.length} ${changed.length === 1 ? "change" : "changes"}.` });
    } catch {
      /* shown in the save bar via update.error */
    }
  }

  async function restore(field: SettingField, label: string) {
    try {
      // null drops the override: the backend falls back to .env.
      await update.mutateAsync({ values: { [field.name]: null } });
      setValue(field.name, undefined);
      setToast({ kind: "ok", message: `${label} is back to its default.` });
    } catch (err) {
      setToast({ kind: "error", message: err instanceof ApiError ? err.message : "Couldn't reset it. Try again." });
    }
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
      <div className="mx-auto max-w-5xl px-6 pt-8">
        <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-5 text-sm">
          <p className="font-medium text-[var(--destructive)]">Couldn&apos;t load settings</p>
          <p className="mt-1 text-[var(--muted-foreground)]">
            {error instanceof ApiError ? error.message : "Check that the backend is running, then try again."}
          </p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      </div>
    );
  }

  const sectionFields = fields
    .filter((f) => fieldMeta(f.name, f.type).section === section.id)
    .sort((a, b) => fieldOrder(a.name) - fieldOrder(b.name));
  const submitError = update.error instanceof ApiError ? update.error.message : update.error ? "Couldn't save. Try again." : null;

  return (
    <div className="mx-auto max-w-6xl px-6 pb-16 pt-8">
      <PageHeader
        icon={Settings}
        title="Settings"
        description="Changes are saved to the database and apply right away — no restart needed. Defaults come from the server's .env file."
      />

      <div className="grid gap-8 md:grid-cols-[13rem_minmax(0,1fr)]">
        {/* Section navigation: a column on desktop, a scrollable row on phones. */}
        {/* min-w-0: a grid item defaults to min-width:auto, so the scrollable
            row of tabs would widen the whole column on phones instead of scrolling. */}
        <nav aria-label="Settings sections" className="min-w-0 md:sticky md:top-6 md:self-start">
          <ul className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 md:flex-col md:overflow-visible">
            {sections.map((s) => {
              const active = s.id === section.id;
              return (
                <li key={s.id} className="shrink-0">
                  <a
                    href={`#${s.id}`}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm outline-none transition",
                      "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                      active
                        ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/60 hover:text-[var(--foreground)]",
                    )}
                  >
                    <s.icon aria-hidden className="size-4 shrink-0" />
                    <span className="flex-1">{s.label}</span>
                    {dirtySections.has(s.id) && (
                      <span className="size-1.5 rounded-full bg-amber-500" title="Unsaved changes">
                        <span className="sr-only">(unsaved changes)</span>
                      </span>
                    )}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <section aria-labelledby="section-title" className="min-w-0">
          <header className="mb-6 border-b pb-4">
            <h2 id="section-title" className="text-lg font-semibold">
              {section.label}
            </h2>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">{section.description}</p>
          </header>

          {section.id === "connections" && <ConnectionsPanel />}
          {section.id === "history" && <HistoryPanel />}

          {section.id === "advanced" && (
            <AdvancedPanel
              busy={busy}
              hasOverrides={Object.keys(data.overrides).length > 0}
              reloading={reloadEnv.isPending}
              onReload={() =>
                void reloadEnv
                  .mutateAsync()
                  .then(() => setToast({ kind: "ok", message: "Reloaded the defaults from .env." }))
                  .catch(() => setToast({ kind: "error", message: "Couldn't reload .env. Try again." }))
              }
              onReset={() => setConfirmReset(true)}
            />
          )}

          {section.id === "keys" && (
            <div className="space-y-3">
              {sectionFields.map((f) => (
                <ApiKeyCard
                  key={f.name}
                  field={f}
                  meta={fieldMeta(f.name, f.type)}
                  draft={typeof draft[f.name] === "string" ? (draft[f.name] as string) : ""}
                  onDraft={(v) => setValue(f.name, v === "" ? undefined : v)}
                  onRestore={() => void restore(f, `The ${fieldMeta(f.name, f.type).label} key`)}
                  busy={busy}
                />
              ))}
            </div>
          )}

          {section.editable && section.id !== "keys" && (
            <div className="divide-y">
              {sectionFields.map((f) => {
                const meta = fieldMeta(f.name, f.type);
                const value = f.name in draft ? draft[f.name] : f.value;
                return (
                  <SettingRow
                    key={f.name}
                    field={f}
                    meta={meta}
                    value={value}
                    error={errors[f.name] ?? null}
                    unsaved={changed.includes(f.name)}
                    busy={busy}
                    onChange={(v) => setValue(f.name, v)}
                    onRestore={() => void restore(f, meta.label)}
                  />
                );
              })}
            </div>
          )}

          {/* Save bar: only while there is something to save. Sticky to the
              content column, not fixed to the window, so it never covers the
              app sidebar. */}
          {(changed.length > 0 || submitError) && (
            <div className="sticky bottom-4 z-10 mt-8">
              <div
                className="flex flex-wrap items-center gap-3 rounded-lg border bg-[var(--background)] px-4 py-3 shadow-lg"
                role="region"
                aria-label="Unsaved changes"
              >
                <div className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                  {submitError ? (
                    <>
                      <CircleAlert aria-hidden className="size-4 shrink-0 text-[var(--destructive)]" />
                      <span role="alert" className="text-[var(--destructive)]">
                        {submitError}
                      </span>
                    </>
                  ) : hasErrors ? (
                    <>
                      <TriangleAlert aria-hidden className="size-4 shrink-0 text-amber-600" />
                      Fix the highlighted {Object.keys(errors).length === 1 ? "field" : "fields"} before saving.
                    </>
                  ) : (
                    <>
                      <span aria-hidden className="size-2 shrink-0 rounded-full bg-amber-500" />
                      {changed.length} unsaved {changed.length === 1 ? "change" : "changes"}
                      {dirtySections.size > 1 && (
                        <span className="text-[var(--muted-foreground)]">across {dirtySections.size} sections</span>
                      )}
                    </>
                  )}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setDraft({});
                    update.reset();
                  }}
                  disabled={busy}
                >
                  <Undo2 aria-hidden />
                  Discard
                </Button>
                <Button size="sm" onClick={() => void save()} disabled={busy || hasErrors || changed.length === 0}>
                  {update.isPending ? <Spinner className="text-current" /> : null}
                  {update.isPending ? "Saving…" : "Save changes"}
                </Button>
              </div>
            </div>
          )}
        </section>
      </div>

      {/* Feedback after an action; aria-live so screen readers announce it. */}
      <div aria-live="polite" className="pointer-events-none fixed bottom-6 right-6 z-50">
        {toast && (
          <div
            className={cn(
              "k8s-fade-in pointer-events-auto flex max-w-sm items-center gap-2 rounded-lg border bg-[var(--background)] px-4 py-3 text-sm shadow-lg",
              toast.kind === "ok"
                ? "border-emerald-500/30 text-emerald-700 dark:text-emerald-400"
                : "border-[var(--destructive)]/40 text-[var(--destructive)]",
            )}
          >
            {toast.kind === "ok" ? <CircleCheck aria-hidden className="size-4" /> : <CircleAlert aria-hidden className="size-4" />}
            {toast.message}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmReset}
        destructive
        title="Reset all settings?"
        description="Every change saved on this page is removed and the system goes back to the values in .env — including API keys added here. The change history is kept."
        confirmLabel={resetAll.isPending ? "Resetting…" : "Reset everything"}
        onConfirm={() => {
          void resetAll
            .mutateAsync()
            .then(() => {
              setDraft({});
              setToast({ kind: "ok", message: "All settings are back to their defaults." });
            })
            .catch(() => setToast({ kind: "error", message: "Couldn't reset the settings. Try again." }))
            .finally(() => setConfirmReset(false));
        }}
        onCancel={() => setConfirmReset(false)}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// One setting: label + help on the left, control on the right (or below, for
// controls that need the full width).
// ---------------------------------------------------------------------------

const WIDE: FieldMeta["control"][] = ["modes", "namespaces"];

function SettingRow({
  field,
  meta,
  value,
  error,
  unsaved,
  busy,
  onChange,
  onRestore,
}: {
  field: SettingField;
  meta: FieldMeta;
  value: unknown;
  error: string | null;
  unsaved: boolean;
  busy: boolean;
  onChange: (value: unknown) => void;
  onRestore: () => void;
}) {
  const id = `setting-${field.name}`;
  const describedBy = [`${id}-help`, error ? `${id}-error` : null].filter(Boolean).join(" ");
  const wide = WIDE.includes(meta.control);
  const props = { id, field, meta, value, onChange, invalid: Boolean(error), describedBy };

  const control =
    meta.control === "slider" ? (
      <SliderControl {...props} />
    ) : meta.control === "number" ? (
      <NumberControl {...props} />
    ) : meta.control === "modes" ? (
      <ModeControl {...props} />
    ) : meta.control === "namespaces" ? (
      <NamespaceControl {...props} />
    ) : (
      <GenericControl {...props} />
    );

  return (
    <div className={cn("grid gap-4 py-5 first:pt-0", !wide && "sm:grid-cols-[minmax(0,1fr)_auto] sm:items-start")}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <label id={`${id}-label`} htmlFor={id} className="text-sm font-medium">
            {meta.label}
          </label>
          {unsaved && <Badge tone="warning">Unsaved</Badge>}
          {!unsaved && field.overridden && <Badge tone="info">Changed from default</Badge>}
        </div>
        <p id={`${id}-help`} className="mt-1 max-w-2xl text-xs leading-relaxed text-[var(--muted-foreground)]">
          {meta.help ?? field.description}
        </p>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-[var(--muted-foreground)]">
          <code>{field.name}</code>
          <span aria-hidden>·</span>
          <span>Default: {formatValue(field.name, field.env_value)}</span>
          {field.overridden && !unsaved && (
            <button
              type="button"
              onClick={onRestore}
              disabled={busy}
              className="inline-flex items-center gap-1 rounded underline underline-offset-2 outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] disabled:opacity-50"
            >
              <RotateCcw aria-hidden className="size-3" />
              Reset to default
            </button>
          )}
        </p>
      </div>

      <div className={cn("min-w-0", !wide && "sm:justify-self-end")}>
        {control}
        {error && (
          <p id={`${id}-error`} className="mt-1.5 text-xs text-[var(--destructive)]">
            {error}
          </p>
        )}
        {meta.control === "modes" && value === "auto" && <ModeWarning />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Advanced: operations on the whole configuration.
// ---------------------------------------------------------------------------

function AdvancedPanel({
  busy,
  hasOverrides,
  reloading,
  onReload,
  onReset,
}: {
  busy: boolean;
  hasOverrides: boolean;
  reloading: boolean;
  onReload: () => void;
  onReset: () => void;
}) {
  return (
    <div className="space-y-6">
      <div className="rounded-lg border p-4">
        <h3 className="text-sm font-medium">How settings are stored</h3>
        <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
          The server&apos;s <code>.env</code> file provides the defaults. Anything changed on this page is saved to the
          database (API keys encrypted) and takes priority over <code>.env</code>, including after a restart.
          Infrastructure addresses — database, Langfuse, Prometheus, Loki, Tempo — are only set in <code>.env</code>.
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border p-4">
        <div className="min-w-0 max-w-prose">
          <h3 className="text-sm font-medium">Reload .env</h3>
          <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
            Read the <code>.env</code> file again after editing it on the server. Changes made on this page stay
            in place on top of it.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onReload} disabled={busy}>
          {reloading ? <Spinner /> : <RotateCcw aria-hidden />}
          Reload .env
        </Button>
      </div>

      <div className="rounded-lg border border-[var(--destructive)]/40">
        <h3 className="border-b border-[var(--destructive)]/30 px-4 py-2.5 text-sm font-medium text-[var(--destructive)]">
          Danger zone
        </h3>
        <div className="flex flex-wrap items-center justify-between gap-4 p-4">
          <div className="min-w-0 max-w-prose">
            <p className="text-sm font-medium">Reset all settings</p>
            <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
              {hasOverrides
                ? "Remove every change made on this page, API keys included, and go back to the .env values."
                : "Nothing to reset — every setting already uses its .env value."}
            </p>
          </div>
          <Button variant="destructive" size="sm" onClick={onReset} disabled={busy || !hasOverrides}>
            Reset all settings
          </Button>
        </div>
      </div>
    </div>
  );
}
