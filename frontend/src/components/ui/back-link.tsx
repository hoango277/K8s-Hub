import Link from "next/link";
import { ArrowLeft } from "lucide-react";

/**
 * "← All diagnoses" above a detail page. A 32px pill hit area: the bare text
 * link it replaces was 20px tall, below the minimum target size.
 */
export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link
      href={href}
      className="-ml-2.5 mb-3 inline-flex h-8 items-center gap-1.5 rounded-full px-2.5 text-sm text-[var(--muted-foreground)] outline-none transition hover:bg-[var(--accent)] hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)] motion-reduce:transition-none"
    >
      <ArrowLeft aria-hidden className="size-4" />
      {children}
    </Link>
  );
}
