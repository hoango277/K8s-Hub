"use client";

import { useEffect, useRef, useState } from "react";
import { CircleAlert, Pencil, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { useUpdateUser } from "@/hooks/use-users";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { User } from "@/types/auth";

/** Matches `display_name: Field(min_length=1, max_length=120)` in backend/app/schemas/auth.py. */
const MAX_NAME = 120;

interface Props {
  user: User | null;
  onClose: () => void;
  onDone: (user: User) => void;
}

/** An admin changes an account's display name — their own included. */
export function EditUserDialog({ user, onClose, onDone }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const update = useUpdateUser();

  const open = user !== null;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  function close() {
    if (update.isPending) return;
    update.reset();
    onClose();
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="edit-user-title"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
      className={cn(
        "m-auto w-[min(28rem,calc(100vw-2rem))] rounded-xl border p-0",
        "bg-[var(--background)] text-[var(--foreground)] shadow-xl",
      )}
    >
      {/* Keyed by account: the form remounts for each person, so the name
          field starts from THEIR current name without syncing state in an
          effect. */}
      {user && <EditForm key={user.id} user={user} update={update} onClose={close} onDone={onDone} />}
    </dialog>
  );
}

function EditForm({
  user,
  update,
  onClose,
  onDone,
}: {
  user: User;
  update: ReturnType<typeof useUpdateUser>;
  onClose: () => void;
  onDone: (user: User) => void;
}) {
  const [name, setName] = useState(user.display_name);

  const trimmed = name.trim();
  const error =
    trimmed.length === 0
      ? "Enter a name."
      : trimmed.length > MAX_NAME
        ? `Use at most ${MAX_NAME} characters.`
        : null;
  const unchanged = trimmed === user.display_name;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (error || unchanged) return;
    update.mutate({ id: user.id, patch: { display_name: trimmed } }, { onSuccess: (updated) => onDone(updated) });
  }

  return (
    <form onSubmit={submit}>
      <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-[var(--accent)]">
            <Pencil aria-hidden className="size-4" />
          </div>
          <div className="min-w-0">
            <h2 id="edit-user-title" className="text-sm font-semibold">
              Edit account
            </h2>
            <p className="truncate text-xs text-[var(--muted-foreground)]">{user.email}</p>
          </div>
        </div>
        <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}>
          <X aria-hidden />
        </Button>
      </div>

      <div className="space-y-4 px-5 py-5">
        <Field id="edit-display-name" label="Display name" error={error}>
          <Input
            id="edit-display-name"
            required
            autoComplete="off"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={update.isPending}
            aria-invalid={Boolean(error)}
            aria-describedby={error ? "edit-display-name-description" : undefined}
          />
        </Field>

        {update.isError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
          >
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {update.error instanceof ApiError ? update.error.message : "Couldn't save the name. Try again."}
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t px-5 py-3">
        <Button variant="outline" onClick={onClose} disabled={update.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={update.isPending || Boolean(error) || unchanged}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
      </div>
    </form>
  );
}
