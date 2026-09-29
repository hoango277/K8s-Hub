"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { CircleAlert, CircleCheck, X } from "lucide-react";

import { cn } from "@/lib/utils";

export interface Toast {
  kind: "ok" | "error";
  message: string;
}

type Show = (toast: Toast) => void;

const ToastContext = createContext<Show | null>(null);

/**
 * One toast at a time, shared by everything under the provider.
 *
 * Mounted in a route LAYOUT (see app/(app)/skills/layout.tsx) rather than in
 * a page, so a message survives client-side navigation — "Deleted X" still
 * shows after the detail page sends you back to the list.
 */
export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<(Toast & { key: number }) | null>(null);

  const show = useCallback<Show>((t) => setToast({ ...t, key: Date.now() }), []);

  // Success disappears on its own; errors linger longer since they usually
  // need reading, and can be closed by hand.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), toast.kind === "ok" ? 4500 : 9000);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <ToastContext.Provider value={show}>
      {children}
      {/* aria-live so screen readers announce the result of an action. */}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-4 bottom-6 z-50 flex justify-end sm:left-auto sm:right-6">
        {toast && (
          <div
            key={toast.key}
            role={toast.kind === "error" ? "alert" : "status"}
            className={cn(
              "k8s-fade-in pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg border bg-[var(--background)] py-3 pl-4 pr-2 text-sm shadow-lg",
              toast.kind === "ok"
                ? "border-emerald-500/30 text-emerald-700 dark:text-emerald-400"
                : "border-[var(--destructive)]/40 text-[var(--destructive)]",
            )}
          >
            {toast.kind === "ok" ? (
              <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            ) : (
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            )}
            <span className="min-w-0 flex-1 break-words">{toast.message}</span>
            <button
              type="button"
              onClick={() => setToast(null)}
              aria-label="Dismiss"
              className="-my-1 flex size-7 shrink-0 items-center justify-center rounded-md text-[var(--muted-foreground)] outline-none hover:bg-[var(--accent)] hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              <X aria-hidden className="size-3.5" />
            </button>
          </div>
        )}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): Show {
  const show = useContext(ToastContext);
  if (!show) throw new Error("useToast must be used inside <ToastProvider>.");
  return show;
}
