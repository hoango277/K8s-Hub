import { cn } from "@/lib/utils";

/** Classes per unified-diff line. The leading +/- stays visible, so the change
 * never relies on color alone. */
function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "font-semibold text-[var(--foreground)]";
  if (line.startsWith("@@")) return "text-[var(--muted-foreground)]";
  if (line.startsWith("+")) return "bg-[var(--success)]/10 text-[var(--success)]";
  if (line.startsWith("-")) return "bg-[var(--destructive)]/10 text-[var(--destructive)]";
  return "text-[var(--foreground)]/80";
}

/**
 * Before/after of the objects a change touches, as the API server's dry-run
 * returned them. Scrolls inside itself so a long manifest never widens the page.
 */
export function ManifestDiff({ diff, className }: { diff: string; className?: string }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <pre
      aria-label="Changes: lines starting with + are added, lines starting with - are removed"
      className={cn(
        "max-h-80 overflow-auto rounded-md border bg-[var(--muted)]/40 py-2 font-mono text-xs leading-relaxed",
        className,
      )}
    >
      {lines.map((line, i) => (
        <div key={i} className={cn("whitespace-pre px-3", lineClass(line))}>
          {line || " "}
        </div>
      ))}
    </pre>
  );
}
