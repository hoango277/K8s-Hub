"use client";

import { useState } from "react";
import { format, formatDistanceToNow } from "date-fns";
import { CircleAlert, CircleCheck, KeyRound, Pencil, UserRound } from "lucide-react";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { PageHeader } from "@/components/ui/page-header";
import { useChangePassword, useCurrentUser, useUpdateProfile } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";
import { ROLES } from "@/lib/roles";
import type { User } from "@/types/auth";

/** Matches `new_password: Field(min_length=8)` in backend/app/schemas/auth.py. */
const MIN_LENGTH = 8;

/** Matches `display_name: Field(max_length=120)` in backend/app/schemas/auth.py. */
const MAX_NAME = 120;

export function AccountPage() {
  const { data: user } = useCurrentUser();

  // AuthGate in the layout already guarantees a user before we get here.
  if (!user) return null;

  return (
    <div className="mx-auto max-w-3xl px-6 pb-16 pt-8">
      <PageHeader
        icon={UserRound}
        title="My account"
        description="Your profile, sign-in details and security."
      />

      <section aria-labelledby="profile" className="mb-6 rounded-xl border">
        <div className="flex flex-wrap items-center gap-4 p-5">
          <Avatar name={user.display_name} className="size-12 text-base" />
          <ProfileName user={user} />
          <Badge tone={ROLES[user.role].tone}>{ROLES[user.role].label}</Badge>
        </div>
        <dl className="grid gap-4 border-t px-5 py-4 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-[var(--muted-foreground)]">Permissions</dt>
            <dd className="mt-0.5">{ROLES[user.role].description}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--muted-foreground)]">Joined</dt>
            <dd className="mt-0.5">{format(new Date(user.created_at), "MMM d, yyyy")}</dd>
          </div>
          <div>
            <dt className="text-xs text-[var(--muted-foreground)]">Last sign-in</dt>
            <dd className="mt-0.5">
              {user.last_login_at
                ? formatDistanceToNow(new Date(user.last_login_at), { addSuffix: true })
                : "—"}
            </dd>
          </div>
        </dl>
      </section>

      <ChangePassword />
    </div>
  );
}

/**
 * Name + email, with an inline "Edit name" mode. Everyone can rename
 * themselves here (PATCH /auth/me); the email stays fixed because it is the
 * sign-in identity.
 */
function ProfileName({ user }: { user: User }) {
  const update = useUpdateProfile();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(user.display_name);
  const [saved, setSaved] = useState(false);

  const trimmed = name.trim();
  const error =
    trimmed.length === 0 ? "Enter a name." : trimmed.length > MAX_NAME ? `Use at most ${MAX_NAME} characters.` : null;

  function start() {
    setName(user.display_name);
    setSaved(false);
    update.reset();
    setEditing(true);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (error) return;
    if (trimmed === user.display_name) {
      setEditing(false);
      return;
    }
    update.mutate(
      { display_name: trimmed },
      {
        onSuccess: () => {
          setEditing(false);
          setSaved(true);
        },
      },
    );
  }

  if (!editing) {
    return (
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h2 id="profile" className="truncate text-base font-semibold">
            {user.display_name}
          </h2>
          <Button variant="ghost" size="sm" onClick={start} aria-label="Edit your display name">
            <Pencil aria-hidden />
            Edit name
          </Button>
        </div>
        <p className="truncate text-sm text-[var(--muted-foreground)]">{user.email}</p>
        {saved && (
          <p role="status" className="mt-1 flex items-center gap-1.5 text-xs text-emerald-700 dark:text-emerald-400">
            <CircleCheck aria-hidden className="size-3.5" />
            Name saved.
          </p>
        )}
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="min-w-0 flex-1 space-y-2">
      <h2 id="profile" className="sr-only">
        Edit your display name
      </h2>
      <Field id="display-name" label="Display name" error={error}>
        <Input
          id="display-name"
          autoFocus
          autoComplete="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") setEditing(false);
          }}
          disabled={update.isPending}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? "display-name-description" : undefined}
        />
      </Field>
      {update.isError && (
        <p role="alert" className="flex items-center gap-1.5 text-sm text-[var(--destructive)]">
          <CircleAlert aria-hidden className="size-4 shrink-0" />
          {update.error instanceof ApiError ? update.error.message : "Couldn't save your name. Try again."}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={update.isPending || Boolean(error)}>
          {update.isPending ? "Saving…" : "Save"}
        </Button>
        <Button variant="outline" size="sm" onClick={() => setEditing(false)} disabled={update.isPending}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ChangePassword() {
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [done, setDone] = useState(false);

  // Check up front what the backend would reject, and report it right under the field.
  const nextError =
    next.length > 0 && next.length < MIN_LENGTH
      ? `Use at least ${MIN_LENGTH} characters.`
      : next.length > 0 && next === current
        ? "The new password must differ from the current one."
        : null;
  const confirmError =
    (submitted || confirm.length >= next.length) && confirm.length > 0 && confirm !== next
      ? "The passwords don't match."
      : null;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    setDone(false);
    if (!current || !next || nextError || confirm !== next) return;

    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          setSubmitted(false);
          setDone(true);
        },
      },
    );
  }

  return (
    <section aria-labelledby="change-password" className="rounded-xl border">
      <div className="flex items-start gap-3 border-b px-5 py-4">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-[var(--accent)]">
          <KeyRound aria-hidden className="size-4" />
        </span>
        <div>
          <h2 id="change-password" className="text-sm font-semibold">
            Change password
          </h2>
          <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
            After changing it, every other device signed in to this account will be signed out.
            This device stays signed in.
          </p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 px-5 py-5">
        <Field id="current-password" label="Current password">
          <PasswordInput
            id="current-password"
            required
            autoComplete="current-password"
            value={current}
            onChange={(e) => {
              setCurrent(e.target.value);
              setDone(false);
            }}
            disabled={change.isPending}
          />
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field id="new-password" label="New password" error={nextError} hint={`At least ${MIN_LENGTH} characters.`}>
            <PasswordInput
              id="new-password"
              required
              autoComplete="new-password"
              value={next}
              onChange={(e) => {
                setNext(e.target.value);
                setDone(false);
              }}
              disabled={change.isPending}
              aria-invalid={Boolean(nextError)}
              aria-describedby="new-password-description"
            />
          </Field>

          <Field id="confirm-password" label="Confirm new password" error={confirmError}>
            <PasswordInput
              id="confirm-password"
              required
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => {
                setConfirm(e.target.value);
                setDone(false);
              }}
              disabled={change.isPending}
              aria-invalid={Boolean(confirmError)}
              aria-describedby={confirmError ? "confirm-password-description" : undefined}
            />
          </Field>
        </div>

        {change.isError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
          >
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {change.error instanceof ApiError ? change.error.message : "Couldn't change your password. Try again."}
          </div>
        )}

        {done && (
          <div
            role="status"
            className="flex items-start gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2.5 text-sm text-emerald-700 dark:text-emerald-400"
          >
            <CircleCheck aria-hidden className="mt-0.5 size-4 shrink-0" />
            Password changed. Other devices have been signed out.
          </div>
        )}

        <div className="flex justify-end">
          <Button type="submit" disabled={change.isPending}>
            {change.isPending ? "Changing…" : "Change password"}
          </Button>
        </div>
      </form>
    </section>
  );
}
