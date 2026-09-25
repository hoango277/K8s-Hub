"use client";

import { CircleAlert, CircleCheck, ExternalLink, KeyRound, RotateCcw } from "lucide-react";
import { useState } from "react";

import type { FieldMeta } from "@/components/settings/meta";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { PasswordInput } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useTestProviderKey } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import type { SettingField } from "@/types/settings";

interface Props {
  field: SettingField;
  meta: FieldMeta;
  /** The key typed but not saved yet ("" = nothing typed). */
  draft: string;
  onDraft: (value: string | undefined) => void;
  /** Drop the key saved on this page and fall back to the .env value. */
  onRestore: () => void;
  busy: boolean;
}

/**
 * One provider's API key.
 *
 * The saved key is never sent back to the browser, so the card shows its
 * STATE instead (set or not, and where it comes from) and offers to replace
 * it. "Test" proves the saved key works by asking the provider for its model
 * list — a free call, and the same one the chat's model picker makes.
 */
export function ApiKeyCard({ field, meta, draft, onDraft, onRestore, busy }: Props) {
  const [editing, setEditing] = useState(false);
  const test = useTestProviderKey();
  const provider = meta.provider;
  const inputId = `setting-${field.name}`;

  const source = !field.is_set ? null : field.overridden ? "Set on this page" : "From the .env file";
  const testResult = test.data;
  const testOk = testResult && testResult.source === "api" && !testResult.error;

  function cancel() {
    setEditing(false);
    onDraft(undefined);
  }

  return (
    <div className="rounded-lg border p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)]">
            <KeyRound aria-hidden className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 id={`${inputId}-label`} className="text-sm font-medium">
                {meta.label}
              </h3>
              {field.is_set ? <Badge tone="success">Configured</Badge> : <Badge tone="warning">Not set</Badge>}
              {draft && <Badge tone="warning">Unsaved</Badge>}
            </div>
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {source ?? "The assistant can't use this provider until a key is added."}
              <span className="mx-1.5" aria-hidden>
                ·
              </span>
              <code className="text-[11px]">{field.name}</code>
            </p>
          </div>
        </div>

        {!editing && (
          <div className="flex flex-wrap items-center gap-1">
            {field.is_set && provider && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => test.mutate(provider.id)}
                disabled={test.isPending || busy}
              >
                {test.isPending ? <Spinner /> : <CircleCheck aria-hidden />}
                Test
              </Button>
            )}
            {field.overridden && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onRestore}
                disabled={busy}
                title="Remove the key saved here and use the one in .env (if any)"
              >
                <RotateCcw aria-hidden />
                Use .env key
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setEditing(true)} disabled={busy}>
              {field.is_set ? "Replace key" : "Add key"}
            </Button>
          </div>
        )}
      </div>

      {editing && (
        <div className="mt-4 space-y-2 border-t pt-4">
          <label htmlFor={inputId} className="text-sm font-medium">
            New {meta.label} key
          </label>
          <PasswordInput
            id={inputId}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            placeholder="Paste the key"
            value={draft}
            onChange={(e) => onDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && cancel()}
            aria-describedby={`${inputId}-hint`}
          />
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p id={`${inputId}-hint`} className="text-xs text-[var(--muted-foreground)]">
              Saved encrypted when you press <strong>Save changes</strong>. It can&apos;t be viewed again afterwards.
              {provider && (
                <>
                  {" "}
                  <a
                    href={provider.keysUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-0.5 underline underline-offset-2 hover:text-[var(--foreground)]"
                  >
                    Get a {provider.name} key
                    <ExternalLink aria-hidden className="size-3" />
                  </a>
                </>
              )}
            </p>
            <Button variant="ghost" size="sm" onClick={cancel}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {/* Test result: the list of models proves the key works end to end. */}
      {!editing && (testResult || test.isError) && (
        <div
          role="status"
          className={
            testOk
              ? "mt-3 flex items-start gap-2 rounded-md bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-400"
              : "mt-3 flex items-start gap-2 rounded-md bg-[var(--destructive)]/10 px-3 py-2 text-xs text-[var(--destructive)]"
          }
        >
          {testOk ? (
            <CircleCheck aria-hidden className="mt-px size-3.5 shrink-0" />
          ) : (
            <CircleAlert aria-hidden className="mt-px size-3.5 shrink-0" />
          )}
          {testOk
            ? `The key works — ${testResult.models.length} models available.`
            : test.isError
              ? test.error instanceof ApiError
                ? test.error.message
                : "Couldn't reach the backend to run the test."
              : `The key didn't work: ${testResult?.error ?? "the provider returned no models"}.`}
        </div>
      )}
    </div>
  );
}
