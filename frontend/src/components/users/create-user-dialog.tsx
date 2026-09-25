"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CircleAlert, UserPlus, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCreateUser } from "@/hooks/use-users";
import { ApiError } from "@/lib/api";
import { ROLES, ROLE_ORDER } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Role, User } from "@/types/auth";

/** Matches `password: Field(min_length=8)` in backend/app/schemas/auth.py. */
const MIN_PASSWORD_LENGTH = 8;

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (user: User) => void;
}

/**
 * Dialog for creating an account on someone else's behalf.
 *
 * Built on `<dialog>` like `ConfirmDialog` — focus trapping, Esc and the
 * backdrop come for free instead of being rebuilt by hand.
 */
export function CreateUserDialog({ open, onClose, onCreated }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  // Keep the dialog element in state (not just a ref) so it can be passed to
  // SelectContent as the portal container — reading ref.current during render
  // may still give null.
  const [container, setContainer] = useState<HTMLDialogElement | null>(null);
  const attachRef = useCallback((el: HTMLDialogElement | null) => {
    ref.current = el;
    setContainer(el);
  }, []);
  const create = useCreateUser();

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  function reset() {
    setName("");
    setEmail("");
    setPassword("");
    setRole("user");
    setSubmitted(false);
    create.reset();
  }

  function close() {
    if (create.isPending) return;
    reset();
    onClose();
  }

  const passwordError =
    password.length > 0 && password.length < MIN_PASSWORD_LENGTH
      ? `Use at least ${MIN_PASSWORD_LENGTH} characters.`
      : null;
  const nameMissing = submitted && !name.trim();

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (!name.trim() || passwordError || password.length === 0) return;

    create.mutate(
      { display_name: name.trim(), email: email.trim(), password, role },
      {
        onSuccess: (user) => {
          reset();
          onCreated(user);
        },
      },
    );
  }

  return (
    <dialog
      ref={attachRef}
      aria-labelledby="create-user-title"
      onCancel={(e) => {
        e.preventDefault();
        close();
      }}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
      className={cn(
        "m-auto w-[min(30rem,calc(100vw-2rem))] rounded-xl border p-0",
        "bg-[var(--background)] text-[var(--foreground)] shadow-xl",
      )}
    >
      <form onSubmit={submit}>
        <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-[var(--accent)]">
              <UserPlus aria-hidden className="size-4" />
            </div>
            <div>
              <h2 id="create-user-title" className="text-sm font-semibold">
                Add account
              </h2>
              <p className="text-xs text-[var(--muted-foreground)]">
                Create an account for someone else and pick their role up front.
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close" onClick={close}>
            <X aria-hidden />
          </Button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <Field id="cu-name" label="Display name" error={nameMissing ? "Enter a display name." : null}>
            <Input
              id="cu-name"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={create.isPending}
              aria-invalid={nameMissing}
              aria-describedby="cu-name-description"
              autoComplete="off"
            />
          </Field>

          <Field id="cu-email" label="Email">
            <Input
              id="cu-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={create.isPending}
              placeholder="name@company.com"
              autoComplete="off"
            />
          </Field>

          <Field
            id="cu-password"
            label="Initial password"
            error={passwordError}
            hint={`At least ${MIN_PASSWORD_LENGTH} characters. Send it to the user privately, not in a shared channel.`}
          >
            <PasswordInput
              id="cu-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={create.isPending}
              aria-invalid={Boolean(passwordError)}
              aria-describedby="cu-password-description"
              autoComplete="new-password"
            />
          </Field>

          <div className="space-y-1.5">
            <span id="cu-role-label" className="text-sm font-medium">
              Role
            </span>
            <Select value={role} onValueChange={(v) => setRole(v as Role)} disabled={create.isPending}>
              <SelectTrigger aria-labelledby="cu-role-label" className="h-9 w-full justify-between text-sm font-normal">
                <SelectValue />
              </SelectTrigger>
              <SelectContent container={container}>
                {ROLE_ORDER.map((r) => (
                  <SelectItem key={r} value={r} description={ROLES[r].description}>
                    {ROLES[r].label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {create.isError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
            >
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
              {create.error instanceof ApiError ? create.error.message : "Couldn't create the account. Try again."}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t px-5 py-3">
          <Button variant="outline" onClick={close} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create account"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
