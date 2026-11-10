import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Small label for status and categories (role, active/locked...).
 *
 * Five tones, by meaning (docs/ke-hoach/he-mau-giao-dien.md): `neutral` for
 * categories that mean nothing good or bad, `accent` for "in progress" and the
 * few things that should stand out, `success` / `warning` / `danger` only for
 * those meanings. Status colors always come with TEXT, never color alone —
 * people with red-green color blindness must still be able to tell "Locked"
 * from "Active".
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--muted)] text-[var(--secondary-foreground)] ring-1 ring-inset ring-[var(--border)]",
        // Outlined, like groq.com's orange pill buttons: the accent differs from the
        // filled status badges by shape too, not only by a hue close to crimson.
        accent: "text-[var(--brand)] ring-1 ring-inset ring-[var(--brand)]/60",
        success: "bg-[var(--success)]/12 text-[var(--success)]",
        warning: "bg-[var(--warning)]/12 text-[var(--warning)]",
        danger: "bg-[var(--destructive)]/10 text-[var(--destructive)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />;
}
