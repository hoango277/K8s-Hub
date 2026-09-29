"use client";

import { useMemo, useState } from "react";
import { CircleCheck, CircleX, Play } from "lucide-react";

import { FormError, OutputBlock, formatDuration, textareaClass } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader, useDialogContainer } from "@/components/ui/dialog";
import { inputClass } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { useRunTool } from "@/hooks/use-tools";
import { cn } from "@/lib/utils";
import type { JsonSchemaObject, JsonSchemaProperty, Tool } from "@/types/tool";

const TITLE_ID = "try-tool-title";
/** Radix Select can't hold "" as a value, so "leave it to the default" needs a marker. */
const DEFAULT_OPTION = "__default__";

// ---------------------------------------------------------------------------
// JSON Schema -> form fields. Pydantic writes `x: str | None = None` as
// {anyOf: [{type: "string"}, {type: "null"}], default: null}, so optional
// fields are unwrapped to their real type first.
// ---------------------------------------------------------------------------

type Kind = "string" | "integer" | "number" | "boolean" | "enum" | "list" | "json";

interface FieldSpec {
  name: string;
  label: string;
  kind: Kind;
  required: boolean;
  options: string[];
  defaultValue: unknown;
  description: string | null;
  minimum?: number;
  maximum?: number;
}

type Value = string | boolean;

function unwrap(prop: JsonSchemaProperty): JsonSchemaProperty {
  if (!prop.anyOf) return prop;
  const real = prop.anyOf.filter((p) => p.type !== "null");
  return real.length === 1 ? { ...real[0], ...prop, anyOf: undefined, type: real[0].type } : prop;
}

function kindOf(prop: JsonSchemaProperty): Kind {
  if (prop.enum && prop.enum.length > 0) return "enum";
  switch (prop.type) {
    case "string":
      return "string";
    case "integer":
      return "integer";
    case "number":
      return "number";
    case "boolean":
      return "boolean";
    case "array":
      return prop.items && ["string", "integer", "number"].includes(prop.items.type ?? "") ? "list" : "json";
    default:
      return "json";
  }
}

function toFields(schema: JsonSchemaObject): FieldSpec[] {
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, raw]) => {
    const prop = unwrap(raw);
    return {
      name,
      label: prop.title ?? name,
      kind: kindOf(prop),
      required: required.has(name),
      options: (prop.enum ?? []).map(String),
      defaultValue: raw.default ?? prop.default,
      description: prop.description ?? raw.description ?? null,
      minimum: prop.minimum,
      maximum: prop.maximum,
    };
  });
}

function initialValue(f: FieldSpec): Value {
  const d = f.defaultValue;
  if (f.kind === "boolean") return d === true;
  if (d === null || d === undefined) return f.kind === "enum" && !f.required ? DEFAULT_OPTION : "";
  if (f.kind === "list" && Array.isArray(d)) return d.join(", ");
  if (f.kind === "json") return JSON.stringify(d, null, 2);
  return String(d);
}

/** Turn the form into the `args` object, or per-field errors. Empty optional
 * fields are left out so the tool's own default applies. */
function buildArgs(fields: FieldSpec[], values: Record<string, Value>) {
  const args: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (f.kind === "boolean") {
      if (f.required || v !== (f.defaultValue === true)) args[f.name] = v;
      continue;
    }
    const text = typeof v === "string" ? v : "";
    if (text.trim() === "" || text === DEFAULT_OPTION) {
      if (f.required) errors[f.name] = "This field is required.";
      continue;
    }
    if (f.kind === "integer" || f.kind === "number") {
      const n = Number(text.trim());
      if (Number.isNaN(n)) errors[f.name] = "Enter a number.";
      else if (f.kind === "integer" && !Number.isInteger(n)) errors[f.name] = "Use a whole number.";
      else if (f.minimum !== undefined && n < f.minimum) errors[f.name] = `Use ${f.minimum} or more.`;
      else if (f.maximum !== undefined && n > f.maximum) errors[f.name] = `Use ${f.maximum} or less.`;
      else args[f.name] = n;
    } else if (f.kind === "list") {
      args[f.name] = text
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
    } else if (f.kind === "json") {
      try {
        args[f.name] = JSON.parse(text);
      } catch {
        errors[f.name] = "Enter valid JSON.";
      }
    } else {
      args[f.name] = text;
    }
  }
  return { args, errors };
}

// ---------------------------------------------------------------------------

export function ToolTryDialog({ tool, onClose }: { tool: Tool | null; onClose: () => void }) {
  const run = useRunTool();

  function close() {
    if (run.isPending) return;
    run.reset();
    onClose();
  }

  return (
    <Dialog open={tool !== null} onClose={close} labelledBy={TITLE_ID} width="40rem">
      {tool && <TryForm key={tool.name} tool={tool} run={run} onClose={close} />}
    </Dialog>
  );
}

function TryForm({ tool, run, onClose }: { tool: Tool; run: ReturnType<typeof useRunTool>; onClose: () => void }) {
  const fields = useMemo(() => toFields(tool.input_schema), [tool.input_schema]);
  const [values, setValues] = useState<Record<string, Value>>(() =>
    Object.fromEntries(fields.map((f) => [f.name, initialValue(f)])),
  );
  const [submitted, setSubmitted] = useState(false);

  const { args, errors } = buildArgs(fields, values);
  const busy = run.isPending;
  const result = run.data;

  function set(name: string, value: Value) {
    setValues((v) => ({ ...v, [name]: value }));
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (Object.keys(errors).length > 0) return;
    run.mutate({ name: tool.name, args });
  }

  return (
    <form onSubmit={submit} noValidate className="flex max-h-[calc(100dvh-2rem)] flex-col">
      <DialogHeader
        id={TITLE_ID}
        icon={Play}
        title={`Try ${tool.title}`}
        subtitle={<code>{tool.name}</code>}
        onClose={onClose}
        closeDisabled={busy}
      />

      <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5">
        <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">{tool.description}</p>

        {fields.length === 0 ? (
          <p className="rounded-md border border-dashed px-3 py-2.5 text-sm text-[var(--muted-foreground)]">
            This tool takes no arguments — just run it.
          </p>
        ) : (
          <fieldset className="space-y-4" disabled={busy}>
            <legend className="sr-only">Arguments</legend>
            {fields.map((f) => (
              <SchemaField
                key={f.name}
                field={f}
                value={values[f.name]}
                error={submitted ? (errors[f.name] ?? null) : null}
                onChange={(v) => set(f.name, v)}
              />
            ))}
          </fieldset>
        )}

        <FormError error={run.error} fallback="Couldn't run the tool. Try again." />

        {result && (
          <section aria-label="Result" className="k8s-fade-in space-y-2">
            <p className="flex flex-wrap items-center gap-2 text-sm">
              {result.ok ? (
                <span className="flex items-center gap-1.5 font-medium text-emerald-700 dark:text-emerald-400">
                  <CircleCheck aria-hidden className="size-4" /> Succeeded
                </span>
              ) : (
                <span className="flex items-center gap-1.5 font-medium text-[var(--destructive)]">
                  <CircleX aria-hidden className="size-4" /> Failed
                </span>
              )}
              <span className="text-xs text-[var(--muted-foreground)]">in {formatDuration(result.duration_ms)}</span>
            </p>
            <OutputBlock text={result.output} />
          </section>
        )}
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Close
        </Button>
        <Button type="submit" disabled={busy}>
          {busy ? <Spinner className="text-current" label="Running" /> : <Play aria-hidden />}
          {busy ? "Running…" : result ? "Run again" : "Run"}
        </Button>
      </DialogFooter>
    </form>
  );
}

function SchemaField({
  field: f,
  value,
  error,
  onChange,
}: {
  field: FieldSpec;
  value: Value;
  error: string | null;
  onChange: (v: Value) => void;
}) {
  const container = useDialogContainer();
  const id = `arg-${f.name}`;
  const hintId = `${id}-hint`;
  const hint =
    f.kind === "list"
      ? [f.description, "Separate values with commas."].filter(Boolean).join(" ")
      : f.description;

  if (f.kind === "boolean") {
    return (
      <div>
        <label className="flex cursor-pointer items-start gap-3">
          <input
            id={id}
            type="checkbox"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
            aria-describedby={hint ? hintId : undefined}
            className="mt-0.5 size-4 accent-[var(--primary)]"
          />
          <span className="text-sm font-medium">
            <code>{f.label}</code>
            {f.required && <RequiredMark />}
          </span>
        </label>
        {hint && (
          <p id={hintId} className="ml-7 mt-1 text-xs text-[var(--muted-foreground)]">
            {hint}
          </p>
        )}
      </div>
    );
  }

  const describedBy = error ? `${id}-error` : hint ? hintId : undefined;

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium">
        <code>{f.label}</code>
        {f.required && <RequiredMark />}
        <span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">{KIND_LABEL[f.kind]}</span>
      </label>

      {f.kind === "enum" ? (
        <Select value={typeof value === "string" ? value : ""} onValueChange={onChange}>
          <SelectTrigger
            id={id}
            className="h-9 w-full justify-between rounded-md px-3 text-sm font-normal"
            aria-invalid={Boolean(error)}
            aria-describedby={describedBy}
          >
            <SelectValue placeholder="Choose a value" />
          </SelectTrigger>
          <SelectContent container={container}>
            {!f.required && <SelectItem value={DEFAULT_OPTION}>Default</SelectItem>}
            {f.options.map((o) => (
              <SelectItem key={o} value={o}>
                {o}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : f.kind === "json" ? (
        <textarea
          id={id}
          rows={4}
          spellCheck={false}
          className={cn(textareaClass, "font-mono text-xs")}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
        />
      ) : (
        <input
          id={id}
          type="text"
          inputMode={f.kind === "integer" ? "numeric" : f.kind === "number" ? "decimal" : undefined}
          autoComplete="off"
          spellCheck={false}
          className={inputClass}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={Boolean(error)}
          aria-describedby={describedBy}
        />
      )}

      {error ? (
        <p id={`${id}-error`} className="text-xs text-[var(--destructive)]">
          {error}
        </p>
      ) : (
        hint && (
          <p id={hintId} className="text-xs text-[var(--muted-foreground)]">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

const KIND_LABEL: Record<Kind, string> = {
  string: "text",
  integer: "whole number",
  number: "number",
  boolean: "yes/no",
  enum: "choice",
  list: "list",
  json: "JSON",
};

function RequiredMark() {
  return (
    <span className="ml-0.5 text-[var(--destructive)]">
      <span aria-hidden>*</span>
      <span className="sr-only">(required)</span>
    </span>
  );
}
