"use client";

import { cn } from "@/lib/utils";
import type { SettingField } from "@/types/settings";

const INPUT =
  "w-full rounded-md border bg-[var(--background)] px-3 py-1.5 text-sm " +
  "outline-none transition focus:ring-2 focus:ring-[var(--ring)] disabled:opacity-50";

interface Props {
  field: SettingField;
  value: unknown;
  onChange: (value: unknown) => void;
  /** Lỗi do máy chủ trả về cho riêng trường này. */
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
            "relative h-6 w-11 shrink-0 rounded-full transition",
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
        <select
          aria-label={field.name}
          className={cls}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {field.options?.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
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
          placeholder={field.is_set ? "•••••••• (đã đặt, nhập để thay)" : "chưa đặt"}
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
          placeholder="ngăn cách bằng dấu phẩy, để trống là tất cả"
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
