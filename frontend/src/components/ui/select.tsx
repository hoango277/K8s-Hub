"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Custom select, replacing the browser's default `<select>`.
 *
 * `<select>` can't style its dropdown list — the browser and OS draw it, so it
 * always looks out of place next to the rest of the UI, and it can't show
 * multiple lines of info per item.
 *
 * Built on Radix instead of from scratch. A "hand-rolled" dropdown looks the
 * same but lacks many things that only show up in real use: arrow-key
 * navigation, type-ahead to jump to an item, Esc to close, focus trapping,
 * screen reader announcements, and flipping upward near the bottom of the
 * screen. Here the picker sits right at the bottom of the chat panel, so
 * flipping happens often.
 */

export const Select = RadixSelect.Root;
export const SelectValue = RadixSelect.Value;

export function SelectTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof RadixSelect.Trigger>) {
  return (
    <RadixSelect.Trigger
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5",
        "bg-[var(--background)] text-xs font-medium outline-none transition",
        "hover:border-[var(--ring)] hover:bg-[var(--accent)]",
        "focus-visible:border-[var(--ring)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        "data-[state=open]:border-[var(--ring)] data-[state=open]:bg-[var(--accent)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
      <RadixSelect.Icon asChild>
        <ChevronDown aria-hidden className="size-3.5 shrink-0 opacity-60" />
      </RadixSelect.Icon>
    </RadixSelect.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  container,
  ...props
}: React.ComponentProps<typeof RadixSelect.Content> & {
  /**
   * Where to render the list. Defaults to `document.body`. If the select is
   * inside a `<dialog>` opened with `showModal()`, you MUST pass that dialog
   * element here: a modal dialog sits on the "top layer" and makes everything
   * outside it inert, so a list rendered in body appears BEHIND the dialog
   * and can't be clicked.
   */
  container?: HTMLElement | null;
}) {
  return (
    <RadixSelect.Portal container={container ?? undefined}>
      <RadixSelect.Content
        // "popper" so the list follows the trigger and flips when out of room.
        // The default mode overlays the trigger and gets clipped near the
        // bottom of the screen.
        position="popper"
        sideOffset={6}
        collisionPadding={12}
        className={cn(
          "z-50 max-h-[min(24rem,var(--radix-select-content-available-height))]",
          "min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border",
          "bg-[var(--popover)] text-[var(--popover-foreground)] shadow-lg",
          "k8s-dropdown",
          className,
        )}
        {...props}
      >
        <RadixSelect.ScrollUpButton className="flex h-6 items-center justify-center bg-[var(--popover)]">
          <ChevronUp aria-hidden className="size-3.5 opacity-60" />
        </RadixSelect.ScrollUpButton>

        <RadixSelect.Viewport className="p-1">{children}</RadixSelect.Viewport>

        <RadixSelect.ScrollDownButton className="flex h-6 items-center justify-center bg-[var(--popover)]">
          <ChevronDown aria-hidden className="size-3.5 opacity-60" />
        </RadixSelect.ScrollDownButton>
      </RadixSelect.Content>
    </RadixSelect.Portal>
  );
}

interface ItemProps extends React.ComponentProps<typeof RadixSelect.Item> {
  /** A small secondary line below, e.g. the vendor and context size. */
  description?: React.ReactNode;
}

export function SelectItem({ className, children, description, ...props }: ItemProps) {
  return (
    <RadixSelect.Item
      className={cn(
        "relative flex cursor-pointer select-none items-start gap-2 rounded-lg",
        "py-1.5 pl-2 pr-2 text-sm outline-none",
        // Radix marks the pointed-at item with data-highlighted — shared by
        // mouse and arrow keys, so no separate hover handling is needed.
        "data-[highlighted]:bg-[var(--accent)] data-[highlighted]:text-[var(--accent-foreground)]",
        "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <span className="flex w-4 shrink-0 justify-center pt-0.5">
        <RadixSelect.ItemIndicator>
          <Check aria-hidden className="size-3.5" />
        </RadixSelect.ItemIndicator>
      </span>

      <span className="min-w-0 flex-1">
        <RadixSelect.ItemText>{children}</RadixSelect.ItemText>
        {description && (
          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
            {description}
          </span>
        )}
      </span>
    </RadixSelect.Item>
  );
}

/** Group heading in the list. NOT USED YET — ready for when models from
    several providers are merged into a single list. */
export function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof RadixSelect.Label>) {
  return (
    <RadixSelect.Label
      className={cn(
        "px-2 py-1.5 text-[11px] font-medium uppercase tracking-wide",
        "text-[var(--muted-foreground)]",
        className,
      )}
      {...props}
    />
  );
}
