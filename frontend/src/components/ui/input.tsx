"use client";

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

import { cn } from "@/lib/utils";

export const inputClass = cn(
  "h-9 w-full rounded-md border bg-[var(--background)] px-3 text-sm outline-none transition",
  "placeholder:text-[var(--muted-foreground)]",
  "focus-visible:border-[var(--ring)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]/40",
  "disabled:cursor-not-allowed disabled:opacity-50",
  "aria-[invalid=true]:border-[var(--destructive)] aria-[invalid=true]:focus-visible:ring-[var(--destructive)]/30",
);

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(inputClass, className)} {...props} />;
}

/** Password field with a show/hide button. The button is `type="button"` so it never submits the form by accident. */
export function PasswordInput({ className, ...props }: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <input type={visible ? "text" : "password"} className={cn(inputClass, "pr-10", className)} {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
        className={cn(
          "absolute inset-y-0 right-0 flex w-9 items-center justify-center rounded-r-md outline-none",
          "text-[var(--muted-foreground)] transition hover:text-[var(--foreground)]",
          "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        )}
      >
        {visible ? <EyeOff aria-hidden className="size-4" /> : <Eye aria-hidden className="size-4" />}
      </button>
    </div>
  );
}

/** Label + input + hint/error line, linked by id for screen readers. */
export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: React.ReactNode;
  error?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {children}
      {(error || hint) && (
        <p
          id={`${id}-description`}
          className={cn("text-xs", error ? "text-[var(--destructive)]" : "text-[var(--muted-foreground)]")}
        >
          {error ?? hint}
        </p>
      )}
    </div>
  );
}
