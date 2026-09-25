"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Set `true` for actions that can't be undone — the confirm button turns red. */
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Confirmation dialog.
 *
 * Built on the browser's `<dialog>` element rather than a `div` with
 * `position: fixed`. Calling `showModal()` gives us four things for free that
 * are easy to miss when rebuilding by hand:
 *
 *   - Focus is trapped inside the dialog; Tab doesn't escape.
 *   - Esc closes it.
 *   - The rest of the page is hidden from screen readers.
 *   - The backdrop is drawn on the top layer, no z-index fights.
 *
 * This replaces `window.confirm()`. The browser's dialog blocks everything
 * else in the tab until the user clicks, and can't follow the app's styling.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  // Sync React state with the dialog element — this is "talking to an
  // external system", exactly what effects are for.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      // The user pressed Esc: the browser closes it on its own, so we must
      // tell React, otherwise the next open won't take effect.
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      // Clicking outside the box closes it. The backdrop IS the dialog
      // element, so a click landing here means it fell outside the content.
      onClick={(e) => {
        if (e.target === ref.current) onCancel();
      }}
      className={cn(
        "m-auto w-[min(26rem,calc(100vw-2rem))] rounded-xl border p-0",
        "bg-[var(--background)] text-[var(--foreground)] shadow-lg",
      )}
    >
      <div className="p-5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description && (
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t px-4 py-3">
        <Button variant="outline" size="sm" onClick={onCancel}>
          {cancelLabel}
        </Button>
        <Button
          variant={destructive ? "destructive" : "primary"}
          size="sm"
          onClick={onConfirm}
          // Focus this button on open, but NOT as the Enter default for
          // destructive actions — the user must click deliberately.
          autoFocus={!destructive}
        >
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
