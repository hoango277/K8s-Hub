"use client";

import { useState } from "react";
import { Eye, ShieldCheck, TriangleAlert, X, Zap } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { inputClass } from "@/components/ui/input";
import { EXECUTION_MODES, type FieldMeta, type ModeOption } from "@/components/settings/meta";
import { cn } from "@/lib/utils";
import type { SettingField } from "@/types/settings";

// ---------------------------------------------------------------------------
// Validation — mirrors the Pydantic bounds the backend enforces, so the user
// sees the problem under the field instead of a 422 after pressing Save.
// ---------------------------------------------------------------------------

export function validate(field: SettingField, value: unknown): string | null {
  if (field.type !== "integer" && field.type !== "number") return null;
  if (value === null || value === undefined || value === "") return "Enter a value.";
  if (typeof value !== "number" || Number.isNaN(value)) return "Enter a number.";
  if (field.type === "integer" && !Number.isInteger(value)) return "Use a whole number.";
  if (field.minimum !== null && value < field.minimum) return `Use ${field.minimum} or more.`;
  if (field.exclusive_minimum !== null && value <= field.exclusive_minimum)
    return `Use a value above ${field.exclusive_minimum}.`;
  if (field.maximum !== null && value > field.maximum) return `Use ${field.maximum} or less.`;
  if (field.exclusive_maximum !== null && value >= field.exclusive_maximum)
    return `Use a value below ${field.exclusive_maximum}.`;
  return null;
}

function parseNumber(raw: string, integer: boolean): number | null {
  if (raw.trim() === "") return null;
  const n = integer ? Number.parseInt(raw, 10) : Number.parseFloat(raw);
  return Number.isNaN(n) ? Number.NaN : n;
}

// Native number spinners sit on top of the unit label and are tiny click
// targets anyway; the arrow keys still step the value.
const NO_SPIN =
  "[appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";

interface ControlProps {
  id: string;
  field: SettingField;
  meta: FieldMeta;
  value: unknown;
  onChange: (value: unknown) => void;
  invalid: boolean;
  describedBy?: string;
}

// ---------------------------------------------------------------------------
// Number with a unit suffix
// ---------------------------------------------------------------------------

export function NumberControl({ id, field, meta, value, onChange, invalid, describedBy }: ControlProps) {
  const integer = field.type === "integer";
  return (
    <div className="relative w-full sm:w-56">
      <input
        id={id}
        type="number"
        inputMode={integer ? "numeric" : "decimal"}
        className={cn(inputClass, NO_SPIN, meta.unit && "pr-20")}
        value={typeof value === "number" && !Number.isNaN(value) ? String(value) : ""}
        step={meta.step ?? (integer ? 1 : 0.1)}
        min={field.minimum ?? field.exclusive_minimum ?? undefined}
        max={field.maximum ?? undefined}
        onChange={(e) => onChange(parseNumber(e.target.value, integer))}
        aria-invalid={invalid}
        aria-describedby={describedBy}
      />
      {meta.unit && (
        <span
          aria-hidden
          className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-[var(--muted-foreground)]"
        >
          {meta.unit}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Slider + exact value (temperature)
// ---------------------------------------------------------------------------

export function SliderControl({ id, field, meta, value, onChange, invalid, describedBy }: ControlProps) {
  const min = field.minimum ?? 0;
  const max = field.maximum ?? 1;
  const step = meta.step ?? 0.1;
  const current = typeof value === "number" && !Number.isNaN(value) ? value : min;

  return (
    <div className="flex w-full items-center gap-4 sm:w-80">
      <div className="flex-1">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={current}
          onChange={(e) => onChange(Number.parseFloat(e.target.value))}
          // The number box next to it carries the label; the slider is the
          // same value, so name it explicitly for screen readers.
          aria-label={`${meta.label} slider`}
          className="h-2 w-full cursor-pointer accent-[var(--primary)]"
        />
        {meta.scale && (
          <div aria-hidden className="mt-1 flex justify-between text-[11px] text-[var(--muted-foreground)]">
            <span>{meta.scale[0]}</span>
            <span>{meta.scale[1]}</span>
          </div>
        )}
      </div>
      <input
        id={id}
        type="number"
        inputMode="decimal"
        className={cn(inputClass, NO_SPIN, "w-20 text-center tabular-nums")}
        min={min}
        max={max}
        step={step}
        value={typeof value === "number" && !Number.isNaN(value) ? String(value) : ""}
        onChange={(e) => onChange(parseNumber(e.target.value, false))}
        aria-invalid={invalid}
        aria-describedby={describedBy}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Execution mode — three cards instead of a dropdown: the difference between
// the options is the whole point, so it must be readable without opening.
// ---------------------------------------------------------------------------

const MODE_ICONS = { read_only: Eye, require_approval: ShieldCheck, auto: Zap } as const;

export function ModeControl({ id, field, value, onChange, describedBy }: ControlProps) {
  const known = new Set(EXECUTION_MODES.map((m) => m.value));
  // Any option the backend adds later still appears, just without a description.
  const options: ModeOption[] = [
    ...EXECUTION_MODES.filter((m) => field.options?.includes(m.value) ?? true),
    ...(field.options ?? []).filter((o) => !known.has(o)).map((o) => ({ value: o, label: o, description: "" })),
  ];

  return (
    <div
      role="radiogroup"
      id={id}
      aria-labelledby={`${id}-label`}
      aria-describedby={describedBy}
      className="grid gap-3 md:grid-cols-3"
    >
      {options.map((opt) => {
        const selected = value === opt.value;
        const Icon = MODE_ICONS[opt.value as keyof typeof MODE_ICONS] ?? ShieldCheck;
        const dangerous = Boolean(opt.dangerous);
        return (
          <label
            key={opt.value}
            className={cn(
              "relative flex cursor-pointer flex-col gap-2 rounded-lg border p-4 transition",
              "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--ring)]",
              selected
                ? dangerous
                  ? "border-[var(--destructive)] bg-[var(--destructive)]/5"
                  : "border-[var(--primary)] bg-[var(--accent)]"
                : "hover:bg-[var(--accent)]/60",
            )}
          >
            <input
              type="radio"
              name={id}
              value={opt.value}
              checked={selected}
              onChange={() => onChange(opt.value)}
              className="sr-only"
            />
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                <Icon
                  aria-hidden
                  className={cn("size-4", dangerous ? "text-[var(--destructive)]" : "text-[var(--muted-foreground)]")}
                />
                {opt.label}
              </span>
              {opt.recommended && <Badge tone="success">Recommended</Badge>}
            </div>
            {opt.description && (
              <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">{opt.description}</p>
            )}
            <span
              aria-hidden
              className={cn(
                "absolute right-3 top-3 size-2 rounded-full",
                selected ? (dangerous ? "bg-[var(--destructive)]" : "bg-[var(--primary)]") : "bg-transparent",
              )}
            />
          </label>
        );
      })}
    </div>
  );
}

export function ModeWarning() {
  return (
    <p
      role="note"
      className="mt-3 flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-xs leading-relaxed text-[var(--destructive)]"
    >
      <TriangleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
      In Automatic mode the assistant changes the cluster with nobody checking first. Use it only on
      clusters you can afford to break.
    </p>
  );
}

// ---------------------------------------------------------------------------
// Namespaces as chips
// ---------------------------------------------------------------------------

/** Kubernetes namespace names are DNS-1123 labels. */
const NAMESPACE_RE = /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/;

export function NamespaceControl({ id, value, onChange, describedBy }: ControlProps) {
  const items = Array.isArray(value) ? (value as string[]) : [];
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  function add(raw: string) {
    const names = raw
      .split(/[,\s]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (names.length === 0) return;
    const bad = names.find((n) => !NAMESPACE_RE.test(n) || n.length > 63);
    if (bad) {
      setError(`"${bad}" isn't a valid namespace name: lowercase letters, digits and "-" only.`);
      return;
    }
    onChange([...items, ...names.filter((n) => !items.includes(n))]);
    setText("");
    setError(null);
  }

  return (
    <div className="w-full">
      <div
        className={cn(
          "flex min-h-9 w-full flex-wrap items-center gap-1.5 rounded-md border bg-[var(--background)] px-2 py-1.5",
          "focus-within:border-[var(--ring)] focus-within:ring-2 focus-within:ring-[var(--ring)]/40",
          error && "border-[var(--destructive)]",
        )}
      >
        {items.map((ns) => (
          <span
            key={ns}
            className="inline-flex items-center gap-1 rounded-md bg-[var(--accent)] py-0.5 pl-2 pr-1 font-mono text-xs"
          >
            {ns}
            <button
              type="button"
              onClick={() => onChange(items.filter((n) => n !== ns))}
              aria-label={`Remove namespace ${ns}`}
              className="flex size-5 items-center justify-center rounded text-[var(--muted-foreground)] outline-none hover:bg-[var(--background)] hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <X aria-hidden className="size-3" />
            </button>
          </span>
        ))}
        <input
          id={id}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(text);
            } else if (e.key === "Backspace" && text === "" && items.length > 0) {
              onChange(items.slice(0, -1));
            }
          }}
          onBlur={() => text && add(text)}
          placeholder={items.length ? "Add another…" : "Type a namespace and press Enter"}
          aria-invalid={Boolean(error)}
          aria-describedby={[describedBy, error ? `${id}-error` : null].filter(Boolean).join(" ") || undefined}
          className="min-w-40 flex-1 bg-transparent px-1 text-sm outline-none placeholder:text-[var(--muted-foreground)]"
        />
      </div>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-xs text-[var(--destructive)]">
          {error}
        </p>
      ) : (
        items.length === 0 && (
          <p className="mt-1.5 text-xs text-[var(--muted-foreground)]">
            No restriction — the assistant may work in every namespace.
          </p>
        )
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fallback for fields without a dedicated control
// ---------------------------------------------------------------------------

export function GenericControl({ id, field, value, onChange, invalid, describedBy }: ControlProps) {
  if (field.type === "boolean") {
    return (
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={Boolean(value)}
        aria-describedby={describedBy}
        onClick={() => onChange(!value)}
        className={cn(
          "relative h-6 w-11 shrink-0 rounded-full outline-none transition",
          "focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]",
          value ? "bg-[var(--primary)]" : "bg-[var(--muted)]",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-5 w-5 rounded-full bg-[var(--background)] shadow transition-all motion-reduce:transition-none",
            value ? "left-[22px]" : "left-0.5",
          )}
        />
      </button>
    );
  }
  if (field.type === "integer" || field.type === "number") {
    return (
      <NumberControl
        id={id}
        field={field}
        meta={{ label: field.name, section: "other", control: "number" }}
        value={value}
        onChange={onChange}
        invalid={invalid}
        describedBy={describedBy}
      />
    );
  }
  return (
    <input
      id={id}
      className={cn(inputClass, "sm:w-80")}
      value={typeof value === "string" ? value : String(value ?? "")}
      onChange={(e) => onChange(e.target.value)}
      aria-invalid={invalid}
      aria-describedby={describedBy}
    />
  );
}
