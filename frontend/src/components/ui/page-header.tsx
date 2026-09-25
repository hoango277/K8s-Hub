import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface Props {
  title: string;
  /** One sentence on what this page is for — clear to a first-time visitor. */
  description?: React.ReactNode;
  icon?: LucideIcon;
  /** The page's primary action, placed on the right. */
  actions?: React.ReactNode;
  className?: string;
}

/** The header of every page — see the UI/UX guidelines section in CLAUDE.md. */
export function PageHeader({ title, description, icon: Icon, actions, className }: Props) {
  return (
    <header className={cn("mb-8 flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="flex min-w-0 items-start gap-3">
        {Icon && (
          <div className="flex size-10 shrink-0 items-center justify-center rounded-lg border bg-[var(--accent)]">
            <Icon aria-hidden className="size-5 text-[var(--foreground)]" />
          </div>
        )}
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {description && (
            <p className="mt-1 max-w-2xl text-sm leading-relaxed text-[var(--muted-foreground)]">
              {description}
            </p>
          )}
        </div>
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  );
}
