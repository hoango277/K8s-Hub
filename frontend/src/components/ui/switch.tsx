"use client";

import { cn } from "@/lib/utils";

interface Props extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, "onChange"> {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** Shows the switch as busy while a save is in flight, so it can't be flipped twice. */
  pending?: boolean;
}

/**
 * On/off switch — a `<button role="switch">`, so Space/Enter toggle it and
 * screen readers announce "on"/"off". Give it an `aria-label` or point
 * `aria-labelledby` at visible text: the switch itself has no words.
 */
export function Switch({ checked, onCheckedChange, pending, disabled, className, ...props }: Props) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-busy={pending || undefined}
      disabled={disabled || pending}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        "relative h-6 w-11 shrink-0 rounded-full outline-none transition motion-reduce:transition-none",
        // The track is 24px tall; the invisible ::after grows the hit area to
        // ~32px so it meets the minimum target size.
        "after:absolute after:-inset-y-1 after:inset-x-0 after:content-['']",
        "focus-visible:ring-2 focus-visible:ring-[var(--ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--background)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "bg-[var(--primary)]" : "bg-[var(--muted)] ring-1 ring-inset ring-[var(--border)]",
        className,
      )}
      {...props}
    >
      <span
        aria-hidden
        className={cn(
          "absolute top-0.5 size-5 rounded-full bg-[var(--background)] shadow transition-all motion-reduce:transition-none",
          checked ? "left-[22px]" : "left-0.5",
        )}
      />
    </button>
  );
}
