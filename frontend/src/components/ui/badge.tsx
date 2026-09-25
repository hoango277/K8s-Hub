import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/**
 * Small label for status and categories (role, active/locked...).
 *
 * Status colors (green/yellow/red) always come with TEXT, never color alone —
 * people with red-green color blindness must still be able to tell "Locked"
 * from "Active".
 */
const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--accent)] text-[var(--accent-foreground)]",
        success: "bg-emerald-500/12 text-emerald-700 dark:text-emerald-400",
        warning: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
        danger: "bg-[var(--destructive)]/12 text-[var(--destructive)]",
        info: "bg-sky-500/12 text-sky-700 dark:text-sky-400",
        violet: "bg-violet-500/12 text-violet-700 dark:text-violet-400",
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
