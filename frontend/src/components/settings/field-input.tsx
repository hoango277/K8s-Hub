"use client";

import { inputClass } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { SettingField } from "@/types/settings";

const INPUT = inputClass;

interface Props {
  field: SettingField;
  value: unknown;
  onChange: (value: unknown) => void;
  /** Error returned by the server for this specific field. */
  error?: string;
}

export function FieldInput({ field, value, onChange, error }: Props) {
  const invalid = Boolean(error);
  const cls = cn(INPUT, invalid && "border-[var(--destructive)]");

  switch (field.type) {
    case "boolean":
      return (
        <button
          type="button"
          role="switch"
          aria-checked={Boolean(value)}
          aria-label={field.name}
          onClick={() => onChange(!value)}
          className={cn(
            "relative h-6 w-11 shrink-0 rounded-full outline-none transition",
            "focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]",
            value ? "bg-[var(--primary)]" : "bg-[var(--muted)]",
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-5 w-5 rounded-full bg-[var(--background)] shadow transition-all",
              value ? "left-[22px]" : "left-0.5",
            )}
          />
        </button>
      );

    case "enum":
      return (
        <Select value={String(value ?? "")} onValueChange={(v) => onChange(v)}>
          <SelectTrigger
            aria-label={field.name}
            aria-invalid={invalid}
            className="h-9 w-full justify-between text-sm font-normal"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.options?.map((opt) => (
              <SelectItem key={opt} value={opt}>
                {opt}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );

    case "integer":
    case "number":
      return (
        <input
          type="number"
          aria-label={field.name}
          className={cls}
          value={value === null || value === undefined ? "" : String(value)}
          step={field.type === "integer" ? 1 : 0.1}
          min={field.minimum ?? undefined}
          max={field.maximum ?? undefined}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") return onChange(null);
            const num = field.type === "integer" ? parseInt(raw, 10) : parseFloat(raw);
            onChange(Number.isNaN(num) ? raw : num);
          }}
        />
      );

    case "secret":
      return (
        <input
          type="password"
          aria-label={field.name}
          className={cls}
          placeholder={field.is_set ? "•••••••• (set — type to replace)" : "Not set"}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          autoComplete="off"
        />
      );

    case "list":
      return (
        <input
          aria-label={field.name}
          className={cls}
          placeholder="Comma-separated; leave blank for all"
          value={Array.isArray(value) ? value.join(", ") : ""}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
        />
      );

    case "object":
      return (
        <textarea
          aria-label={field.name}
          rows={8}
          spellCheck={false}
          className={cn(cls, "font-mono text-xs leading-relaxed")}
          value={typeof value === "string" ? value : JSON.stringify(value ?? {}, null, 2)}
          onChange={(e) => onChange(e.target.value)}
        />
      );

    default:
      return (
        <input
          aria-label={field.name}
          className={cls}
          value={typeof value === "string" ? value : String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
      );
  }
}
