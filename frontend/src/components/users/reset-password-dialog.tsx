"use client";

import { useEffect, useRef, useState } from "react";
import { Check, CircleAlert, Copy, KeyRound, RefreshCw, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Field, PasswordInput } from "@/components/ui/input";
import { useResetPassword } from "@/hooks/use-users";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { User } from "@/types/auth";

/** Matches `new_password: Field(min_length=8)` in backend/app/schemas/auth.py. */
const MIN_LENGTH = 8;

/** Leaves out easily confused characters (0/O, 1/l/I) — temporary passwords
 * are often read out over the phone or retyped from a message. */
const ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789";

function generatePassword(length = 14): string {
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  return Array.from(values, (n) => ALPHABET[n % ALPHABET.length]).join("");
}

interface Props {
  user: User | null;
  onClose: () => void;
  onDone: (user: User) => void;
}

/**
 * An admin resets someone else's password — for when they've forgotten it.
 * All of that person's sessions are signed out immediately (the backend
 * handles that).
 */
export function ResetPasswordDialog({ user, onClose, onDone }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const resetPassword = useResetPassword();
  const [password, setPassword] = useState("");
  const [copied, setCopied] = useState(false);

  const open = user !== null;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  function close() {
    if (resetPassword.isPending) return;
    setPassword("");
    setCopied(false);
    resetPassword.reset();
    onClose();
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(password);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // The browser blocked the clipboard (insecure page, permission revoked) —
      // the user can still reveal the password and copy it by hand, so no need
      // for a loud error.
    }
  }

  const error =
    password.length > 0 && password.length < MIN_LENGTH ? `Use at least ${MIN_LENGTH} characters.` : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!user || !password || error) return;
    resetPassword.mutate(
      { id: user.id, new_password: password },
      {
        onSuccess: () => {
          const u = user;
          setPassword("");
          setCopied(false);
          onDone(u);
        },
      },
    );
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="reset-password-title"
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
      <form onSubmit={submit}>
        <div className="flex items-start justify-between gap-4 border-b px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg bg-[var(--accent)]">
              <KeyRound aria-hidden className="size-4" />
            </div>
            <div className="min-w-0">
              <h2 id="reset-password-title" className="text-sm font-semibold">
                Reset password
              </h2>
              <p className="truncate text-xs text-[var(--muted-foreground)]">
                {user?.display_name} · {user?.email}
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" aria-label="Close" onClick={close}>
            <X aria-hidden />
          </Button>
        </div>

        <div className="space-y-4 px-5 py-5">
          <Field
            id="temp-password"
            label="New password"
            error={error}
            hint="Send it to the user privately, and remind them to change it on the Account page after signing in."
          >
            <PasswordInput
              id="temp-password"
              required
              autoComplete="new-password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setCopied(false);
              }}
              disabled={resetPassword.isPending}
              aria-invalid={Boolean(error)}
              aria-describedby="temp-password-description"
            />
          </Field>

          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setPassword(generatePassword());
                setCopied(false);
              }}
              disabled={resetPassword.isPending}
            >
              <RefreshCw aria-hidden />
              Generate
            </Button>
            <Button variant="outline" size="sm" onClick={() => void copy()} disabled={!password}>
              {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
              {copied ? "Copied" : "Copy"}
            </Button>
          </div>

          <p className="rounded-md bg-amber-500/10 px-3 py-2.5 text-xs leading-relaxed text-amber-800 dark:text-amber-300">
            This person will be signed out of every device as soon as you confirm.
          </p>

          {resetPassword.isError && (
            <div
              role="alert"
              className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
            >
              <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
              {resetPassword.error instanceof ApiError
                ? resetPassword.error.message
                : "Couldn't reset the password. Try again."}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 border-t px-5 py-3">
          <Button variant="outline" onClick={close} disabled={resetPassword.isPending}>
            Cancel
          </Button>
          <Button type="submit" disabled={resetPassword.isPending || !password || Boolean(error)}>
            {resetPassword.isPending ? "Resetting…" : "Reset password"}
          </Button>
        </div>
      </form>
    </dialog>
  );
}
