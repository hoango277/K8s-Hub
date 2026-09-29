"use client";

import { createContext, useContext, useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * The open `<dialog>` element, for Radix portals inside it. A modal dialog
 * sits on the top layer and makes the rest of the page inert, so a Select
 * list rendered in `document.body` would appear BEHIND it and be unclickable
 * — pass `useDialogContainer()` as `SelectContent`'s `container`.
 */
const DialogContainer = createContext<HTMLElement | null>(null);

export function useDialogContainer(): HTMLElement | null {
  return useContext(DialogContainer);
}

interface Props {
  open: boolean;
  /** Called on Esc, a click on the backdrop, or the close button. Ignore it while saving. */
  onClose: () => void;
  labelledBy: string;
  /** Tailwind width token, e.g. "32rem". */
  width?: string;
  children: React.ReactNode;
}

/**
 * Modal dialog on the native `<dialog>` element — same approach as
 * ConfirmDialog: `showModal()` traps focus, closes on Esc, hides the page from
 * screen readers and draws on the top layer without z-index fights.
 *
 * Children only mount while open, so each opening starts from a fresh form
 * instead of last time's half-typed values.
 */
export function Dialog({ open, onClose, labelledBy, width = "32rem", children }: Props) {
  // State rather than a ref, so the Select-container context re-renders
  // consumers once the element exists. `setEl` is stable, so React doesn't
  // detach and re-attach the ref on every render.
  const [el, setEl] = useState<HTMLDialogElement | null>(null);

  useEffect(() => {
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open, el]);

  return (
    <dialog
      ref={setEl}
      aria-labelledby={labelledBy}
      onCancel={(e) => {
        // The browser would close it on its own; let React state decide instead.
        e.preventDefault();
        onClose();
      }}
      onClick={(e) => {
        if (e.target === el) onClose();
      }}
      style={{ width: `min(${width}, calc(100vw - 2rem))` }}
      className={cn(
        "m-auto max-h-[calc(100dvh-2rem)] rounded-xl border p-0",
        "bg-[var(--background)] text-[var(--foreground)] shadow-xl",
      )}
    >
      <DialogContainer.Provider value={el}>{open && children}</DialogContainer.Provider>
    </dialog>
  );
}

export function DialogHeader({
  id,
  icon: Icon,
  title,
  subtitle,
  onClose,
  closeDisabled,
}: {
  id: string;
  icon: LucideIcon;
  title: string;
  subtitle?: React.ReactNode;
  onClose: () => void;
  closeDisabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)]">
          <Icon aria-hidden className="size-4" />
        </div>
        <div className="min-w-0">
          <h2 id={id} className="text-sm font-semibold">
            {title}
          </h2>
          {subtitle && <p className="text-xs text-[var(--muted-foreground)]">{subtitle}</p>}
        </div>
      </div>
      <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose} disabled={closeDisabled}>
        <X aria-hidden />
      </Button>
    </div>
  );
}

export function DialogFooter({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap justify-end gap-2 border-t px-5 py-3">{children}</div>;
}
