"use client";

import { cn } from "@/lib/utils";

export interface ChipOption<T> {
  value: T;
  label: string;
}

/**
 * A single-choice filter shown as a row of pill chips (groq.com-style pills).
 *
 * One component for every list filter (diagnoses, approvals, users): they used
 * to be three hand-written variants, one of them a `radiogroup` without the
 * arrow-key handling that role promises. Toggle buttons with `aria-pressed`
 * are simpler and honest: each chip is one Tab stop and says whether it is on.
 */
export function ChipGroup<T extends string | null>({
  label,
  options,
  value,
  onChange,
  className,
}: {
  /** What the chips filter, for screen readers ("Filter by status"). */
  label: string;
  options: ChipOption<T>[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div role="group" aria-label={label} className={cn("flex flex-wrap gap-1.5", className)}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.label}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "h-8 rounded-full border px-3.5 text-sm font-medium outline-none transition motion-reduce:transition-none",
              "focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]",
              active
                ? "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]"
                : "border-[var(--input)] bg-[var(--background)] text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
