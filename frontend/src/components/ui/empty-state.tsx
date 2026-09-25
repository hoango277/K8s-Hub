import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: React.ReactNode;
  /** A button or link pointing the user to the next step. */
  children?: React.ReactNode;
  className?: string;
}

/**
 * Empty state — instead of a bare "No data" line or a blank page.
 *
 * Always answers two questions: why this area is empty, and what to do next.
 */
export function EmptyState({ icon: Icon, title, description, children, className }: Props) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border border-dashed px-6 py-14 text-center",
        className,
      )}
    >
      <div className="mb-4 flex size-12 items-center justify-center rounded-full bg-[var(--accent)]">
        <Icon aria-hidden className="size-6 text-[var(--muted-foreground)]" />
      </div>
      <h2 className="text-base font-semibold">{title}</h2>
      {description && (
        <div className="mt-1.5 max-w-md text-sm leading-relaxed text-[var(--muted-foreground)]">
          {description}
        </div>
      )}
      {children && <div className="mt-5 flex flex-wrap justify-center gap-2">{children}</div>}
    </div>
  );
}
