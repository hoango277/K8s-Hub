import Link from "next/link";
import { Check, Construction, type LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";

interface Props {
  icon: LucideIcon;
  title: string;
  description: string;
  /** What this page will be able to do — so visitors understand the feature
   * instead of just seeing an "in development" line. */
  feature: string[];
}

/**
 * Page for a feature that isn't built yet. Per the UI/UX guidelines in
 * CLAUDE.md: never leave a blank page (`return null`); say what the page will
 * do and point to something usable right now.
 */
export function ComingSoon({ icon, title, description, feature }: Props) {
  return (
    <div className="mx-auto max-w-4xl px-6 pb-16 pt-8">
      <PageHeader icon={icon} title={title} description={description} actions={<Badge tone="warning">In development</Badge>} />

      <section className="overflow-hidden rounded-xl border">
        <div className="flex items-center gap-3 border-b bg-[var(--muted)]/40 px-5 py-4">
          <span className="flex size-9 items-center justify-center rounded-lg bg-amber-500/15 text-amber-700 dark:text-amber-400">
            <Construction aria-hidden className="size-4" />
          </span>
          <div>
            <h2 className="text-sm font-semibold">This feature is being built</h2>
            <p className="text-xs text-[var(--muted-foreground)]">Here&apos;s what the page will do.</p>
          </div>
        </div>

        <ul className="grid gap-x-6 gap-y-3 px-5 py-5 sm:grid-cols-2">
          {feature.map((t) => (
            <li key={t} className="flex items-start gap-2.5 text-sm">
              <Check aria-hidden className="mt-0.5 size-4 shrink-0 text-[var(--muted-foreground)]" />
              <span>{t}</span>
            </li>
          ))}
        </ul>

        <div className="flex flex-wrap items-center justify-between gap-3 border-t px-5 py-4">
          <p className="text-sm text-[var(--muted-foreground)]">
            In the meantime, you can ask the assistant directly in Chat.
          </p>
          <Link href="/chat" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Open Chat
          </Link>
        </div>
      </section>
    </div>
  );
}
