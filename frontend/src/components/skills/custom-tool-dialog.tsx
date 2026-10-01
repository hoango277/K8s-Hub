"use client";

import { useId, useState } from "react";
import { Terminal } from "lucide-react";

import {
  FormError,
  parseReadPrefixes,
  textareaClass,
  validateCommand,
  validateToolName,
} from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader, useDialogContainer } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useCreateCustomTool, useCustomToolTemplates, useUpdateCustomTool } from "@/hooks/use-tools";
import type { CustomTool } from "@/types/tool";

const DESCRIPTION_MIN = 10;
const DESCRIPTION_MAX = 1000;
const USAGE_MAX = 4000;
const TIMEOUT_MIN = 5;
const TIMEOUT_MAX = 300;
const BLANK = "__blank";

interface FormState {
  name: string;
  title: string;
  command: string;
  description: string;
  usage: string;
  prefixes: string;
  timeout: string;
  enabled: boolean;
}

function fromTool(t: CustomTool | null): FormState {
  return {
    name: t?.name ?? "",
    title: t?.title ?? "",
    command: t?.command ?? "",
    description: t?.description ?? "",
    usage: t?.usage ?? "",
    prefixes: (t?.read_only_prefixes ?? []).join("\n"),
    timeout: String(t?.timeout_seconds ?? 60),
    enabled: t?.enabled ?? true,
  };
}

/**
 * Create or edit a custom CLI tool (kubectl-ai style). The engineer fixes the
 * program and lists its read-only subcommands; the assistant only writes the
 * arguments, and any call that isn't read-only waits for approval.
 */
export function CustomToolDialog({
  open,
  editing,
  takenNames,
  onClose,
}: {
  open: boolean;
  /** null = create a new one. */
  editing: CustomTool | null;
  takenNames: string[];
  onClose: () => void;
}) {
  const titleId = useId();
  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId} width="40rem">
      <CustomToolForm titleId={titleId} editing={editing} takenNames={takenNames} onClose={onClose} />
    </Dialog>
  );
}

function CustomToolForm({
  titleId,
  editing,
  takenNames,
  onClose,
}: {
  titleId: string;
  editing: CustomTool | null;
  takenNames: string[];
  onClose: () => void;
}) {
  const creating = editing === null;
  const [form, setForm] = useState<FormState>(() => fromTool(editing));
  const [submitted, setSubmitted] = useState(false);
  const templates = useCustomToolTemplates(creating);
  // The Select list must render inside the modal dialog, or it opens behind it.
  const dialogContainer = useDialogContainer();
  const create = useCreateCustomTool();
  const update = useUpdateCustomTool();
  const mutation = creating ? create : update;
  const toast = useToast();
  const ids = {
    template: useId(),
    name: useId(),
    title: useId(),
    command: useId(),
    description: useId(),
    usage: useId(),
    prefixes: useId(),
    timeout: useId(),
  };

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const parsed = parseReadPrefixes(form.prefixes);
  const timeout = Number(form.timeout);
  const description = form.description.trim();
  const errors = {
    name: creating ? validateToolName(form.name, takenNames) : null,
    title: form.title.trim() ? null : "Enter a title people will recognise.",
    command: validateCommand(form.command),
    description:
      description.length < DESCRIPTION_MIN
        ? "Say when the assistant should use it (at least 10 characters)."
        : description.length > DESCRIPTION_MAX
          ? `Keep it under ${DESCRIPTION_MAX} characters.`
          : null,
    usage: form.usage.length > USAGE_MAX ? `Keep it under ${USAGE_MAX} characters.` : null,
    prefixes: parsed.error,
    timeout:
      Number.isInteger(timeout) && timeout >= TIMEOUT_MIN && timeout <= TIMEOUT_MAX
        ? null
        : `A whole number of seconds from ${TIMEOUT_MIN} to ${TIMEOUT_MAX}.`,
  };
  const invalid = Object.values(errors).some(Boolean);
  // Show a field's error once the user typed in it or tried to submit.
  const show = (key: keyof typeof errors, value: string) =>
    submitted || value.length > 0 ? errors[key] : null;

  function applyTemplate(name: string) {
    if (name === BLANK) {
      setForm(fromTool(null));
      return;
    }
    const t = templates.data?.find((x) => x.name === name);
    if (t) setForm(fromTool(t));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (invalid) return;
    const fields = {
      title: form.title.trim(),
      description,
      command: form.command.trim(),
      usage: form.usage.trim(),
      read_only_prefixes: parsed.prefixes,
      timeout_seconds: timeout,
      enabled: form.enabled,
    };
    const done = () => {
      toast({
        kind: "ok",
        message: creating
          ? `${fields.title} added.${fields.enabled ? " The assistant can use it now." : ""}`
          : `${fields.title} saved.`,
      });
      onClose();
    };
    if (creating) create.mutate({ name: form.name.trim(), ...fields }, { onSuccess: done });
    else update.mutate({ name: editing.name, fields }, { onSuccess: done });
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogHeader
        id={titleId}
        icon={Terminal}
        title={creating ? "New custom tool" : `Edit ${editing.title}`}
        subtitle="Wrap a command-line tool so the assistant can use it."
        onClose={onClose}
        closeDisabled={mutation.isPending}
      />

      <div className="max-h-[65dvh] space-y-4 overflow-y-auto px-5 py-4">
        {creating && (templates.data?.length ?? 0) > 0 && (
          <div className="space-y-1.5">
            <label htmlFor={ids.template} className="text-sm font-medium">
              Start from
            </label>
            <Select defaultValue={BLANK} onValueChange={applyTemplate}>
              <SelectTrigger id={ids.template} className="w-full justify-between">
                <SelectValue />
              </SelectTrigger>
              <SelectContent container={dialogContainer}>
                <SelectItem value={BLANK}>Blank tool</SelectItem>
                {templates.data!.map((t) => (
                  <SelectItem key={t.name} value={t.name} description={t.description}>
                    {t.title}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          {creating ? (
            <Field
              id={ids.name}
              label="Name"
              hint="What the assistant calls it. Can't be changed later."
              error={show("name", form.name)}
            >
              <Input
                id={ids.name}
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="kubectl"
                autoComplete="off"
                aria-invalid={Boolean(show("name", form.name))}
                aria-describedby={`${ids.name}-description`}
              />
            </Field>
          ) : (
            <div className="space-y-1.5">
              <p className="text-sm font-medium">Name</p>
              <code className="block rounded-md bg-[var(--muted)] px-3 py-2 text-sm">{editing.name}</code>
            </div>
          )}
          <Field id={ids.title} label="Title" error={show("title", form.title)}>
            <Input
              id={ids.title}
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              maxLength={120}
              aria-invalid={Boolean(show("title", form.title))}
              aria-describedby={`${ids.title}-description`}
            />
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={ids.command}
            label="Program"
            hint="Installed in the sandbox, e.g. kubectl or helm."
            error={show("command", form.command)}
          >
            <Input
              id={ids.command}
              value={form.command}
              onChange={(e) => set("command", e.target.value)}
              placeholder="kubectl"
              autoComplete="off"
              className="font-mono"
              aria-invalid={Boolean(show("command", form.command))}
              aria-describedby={`${ids.command}-description`}
            />
          </Field>
          <Field
            id={ids.timeout}
            label="Time limit (seconds)"
            hint="The command is stopped after this long."
            error={show("timeout", form.timeout)}
          >
            <Input
              id={ids.timeout}
              type="number"
              inputMode="numeric"
              min={TIMEOUT_MIN}
              max={TIMEOUT_MAX}
              value={form.timeout}
              onChange={(e) => set("timeout", e.target.value)}
              aria-invalid={Boolean(show("timeout", form.timeout))}
              aria-describedby={`${ids.timeout}-description`}
            />
          </Field>
        </div>

        <Field
          id={ids.description}
          label="When to use it"
          hint="The assistant reads this to decide when to call the tool."
          error={show("description", form.description)}
        >
          <textarea
            id={ids.description}
            rows={2}
            value={form.description}
            onChange={(e) => set("description", e.target.value)}
            className={textareaClass}
            aria-invalid={Boolean(show("description", form.description))}
            aria-describedby={`${ids.description}-description`}
          />
        </Field>

        <Field
          id={ids.usage}
          label="Usage and examples"
          hint="Syntax, examples, and what to avoid. Runs without a shell: no pipes or redirects."
          error={show("usage", form.usage)}
        >
          <textarea
            id={ids.usage}
            rows={4}
            value={form.usage}
            onChange={(e) => set("usage", e.target.value)}
            className={`${textareaClass} font-mono text-xs`}
            aria-invalid={Boolean(show("usage", form.usage))}
            aria-describedby={`${ids.usage}-description`}
          />
        </Field>

        <Field
          id={ids.prefixes}
          label="Read-only subcommands"
          hint="One per line, e.g. get or rollout status. These run at once; anything else waits for an engineer's approval."
          error={show("prefixes", form.prefixes)}
        >
          <textarea
            id={ids.prefixes}
            rows={4}
            value={form.prefixes}
            onChange={(e) => set("prefixes", e.target.value)}
            className={`${textareaClass} font-mono text-xs`}
            placeholder={"get\ndescribe\nrollout status"}
            aria-invalid={Boolean(show("prefixes", form.prefixes))}
            aria-describedby={`${ids.prefixes}-description`}
          />
        </Field>

        <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2.5">
          <div>
            <p className="text-sm font-medium">Enabled</p>
            <p className="text-xs text-[var(--muted-foreground)]">Only enabled tools reach the assistant.</p>
          </div>
          <Switch
            checked={form.enabled}
            onCheckedChange={(v) => set("enabled", v)}
            aria-label={form.enabled ? "Disable this tool" : "Enable this tool"}
          />
        </div>

        <FormError error={mutation.error} fallback="Couldn't save the tool. Try again." />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={mutation.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={mutation.isPending || (submitted && invalid)}>
          {mutation.isPending && <Spinner />}
          {creating ? "Add tool" : "Save changes"}
        </Button>
      </DialogFooter>
    </form>
  );
}
