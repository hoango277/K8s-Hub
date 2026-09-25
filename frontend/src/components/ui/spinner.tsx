import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

/** Loading spinner. Uses the `k8s-spin` class, so it stops when "reduce motion" is on. */
export function Spinner({ className, label = "Loading" }: { className?: string; label?: string }) {
  return (
    <LoaderCircle
      role="status"
      aria-label={label}
      className={cn("k8s-spin size-4 text-[var(--muted-foreground)]", className)}
    />
  );
}
