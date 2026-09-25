"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { formatDistanceToNow } from "date-fns";
import {
  KeyRound,
  Lock,
  LockOpen,
  Pencil,
  Search,
  SearchX,
  ShieldCheck,
  UserPlus,
  Users,
  Wrench,
} from "lucide-react";

import { CreateUserDialog } from "@/components/users/create-user-dialog";
import { EditUserDialog } from "@/components/users/edit-user-dialog";
import { ResetPasswordDialog } from "@/components/users/reset-password-dialog";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useCurrentUser } from "@/hooks/use-auth";
import { useUpdateUser, useUsers } from "@/hooks/use-users";
import { ApiError } from "@/lib/api";
import { ROLES, ROLE_ORDER } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Role, User } from "@/types/auth";

type Filter = "all" | Role | "locked";

/** Action waiting for the user to confirm. Changing a role and locking an
 * account both have to go through a confirm dialog — see the UI/UX rules in
 * CLAUDE.md. */
type PendingAction =
  | { kind: "role"; user: User; newRole: Role }
  | { kind: "lock"; user: User }
  | { kind: "unlock"; user: User };

interface Toast {
  kind: "ok" | "error";
  message: string;
}

function lastLogin(iso: string | null): string {
  if (!iso) return "Never signed in";
  return formatDistanceToNow(new Date(iso), { addSuffix: true });
}

export function UserAdmin() {
  const { data: users, isLoading, error, refetch } = useUsers();
  const { data: me } = useCurrentUser();
  const update = useUpdateUser();
  const busy = update.isPending;

  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const [resetTarget, setResetTarget] = useState<User | null>(null);
  const [editTarget, setEditTarget] = useState<User | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);

  // Toasts dismiss themselves after a few seconds — long enough to read,
  // without lingering over the UI.
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 4500);
    return () => clearTimeout(t);
  }, [toast]);

  const stats = useMemo(() => {
    const list = users ?? [];
    return {
      total: list.length,
      admin: list.filter((u) => u.role === "admin").length,
      engineer: list.filter((u) => u.role === "engineer").length,
      locked: list.filter((u) => !u.is_active).length,
    };
  }, [users]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (users ?? []).filter((u) => {
      if (filter === "locked" && u.is_active) return false;
      if (filter !== "all" && filter !== "locked" && u.role !== filter) return false;
      if (!q) return true;
      return u.email.toLowerCase().includes(q) || u.display_name.toLowerCase().includes(q);
    });
  }, [users, query, filter]);

  function runPending() {
    if (!pending) return;
    const { user } = pending;

    const patch =
      pending.kind === "role"
        ? { role: pending.newRole }
        : { is_active: pending.kind === "unlock" };

    update.mutate(
      { id: user.id, patch },
      {
        onSuccess: () => {
          const message =
            pending.kind === "role"
              ? `Changed ${user.display_name} to ${ROLES[pending.newRole].label}.`
              : pending.kind === "lock"
                ? `Locked ${user.display_name}. All of their sessions were signed out.`
                : `Unlocked ${user.display_name}.`;
          setToast({ kind: "ok", message });
        },
        onError: (err) =>
          setToast({
            kind: "error",
            message: err instanceof ApiError ? err.message : "Couldn't complete that. Try again.",
          }),
        onSettled: () => setPending(null),
      },
    );
  }

  const dialog = describeDialog(pending);

  return (
    <div className="mx-auto max-w-6xl px-6 pb-16 pt-8">
      <PageHeader
        icon={Users}
        title="Users"
        description="Add, edit and lock accounts. Self-registered people always start with the User role — promote them here."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <UserPlus aria-hidden />
            Add account
          </Button>
        }
      />

      {/* Quick stats */}
      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Total accounts" value={stats.total} icon={Users} isLoading={isLoading} />
        <StatCard label="Admins" value={stats.admin} icon={ShieldCheck} isLoading={isLoading} />
        <StatCard label="Engineers" value={stats.engineer} icon={Wrench} isLoading={isLoading} />
        <StatCard label="Locked" value={stats.locked} icon={Lock} isLoading={isLoading} />
      </div>

      {/* Filter bar */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="relative w-full sm:w-72">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]"
          />
          <label htmlFor="user-search" className="sr-only">
            Search by name or email
          </label>
          <input
            id="user-search"
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by name or email…"
            className="h-9 w-full rounded-md border bg-[var(--background)] pl-9 pr-3 text-sm outline-none transition placeholder:text-[var(--muted-foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          />
        </div>

        <div role="radiogroup" aria-label="Filter by role" className="flex flex-wrap gap-1 rounded-lg border p-1">
          {(
            [
              ["all", "All"],
              ["admin", ROLES.admin.label],
              ["engineer", ROLES.engineer.label],
              ["user", ROLES.user.label],
              ["locked", "Locked"],
            ] as [Filter, string][]
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={filter === value}
              onClick={() => setFilter(value)}
              className={cn(
                "h-7 rounded-md px-2.5 text-xs font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                filter === value
                  ? "bg-[var(--primary)] text-[var(--primary-foreground)] shadow-sm"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {error ? (
        <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-5">
          <p className="text-sm font-medium text-[var(--destructive)]">Couldn&apos;t load accounts</p>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {error instanceof ApiError ? error.message : "Check that the backend is running, then try again."}
          </p>
          <Button variant="outline" size="sm" className="mt-3" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <thead className="border-b bg-[var(--muted)]/50 text-left text-xs font-medium text-[var(--muted-foreground)]">
                <tr>
                  <th scope="col" className="px-4 py-2.5 font-medium">Account</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Role</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-4 py-2.5 font-medium">Last sign-in</th>
                  <th scope="col" className="px-4 py-2.5 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {isLoading
                  ? Array.from({ length: 4 }, (_, i) => <SkeletonRow key={i} />)
                  : visible.map((u) => {
                      const isMe = u.id === me?.id;
                      return (
                        <tr key={u.id} className={cn("transition hover:bg-[var(--muted)]/40", !u.is_active && "opacity-70")}>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-3">
                              <Avatar name={u.display_name} />
                              <div className="min-w-0">
                                <div className="flex items-center gap-2">
                                  <span className="truncate font-medium">{u.display_name}</span>
                                  {isMe && <Badge>You</Badge>}
                                </div>
                                <span className="block truncate text-xs text-[var(--muted-foreground)]">{u.email}</span>
                              </div>
                            </div>
                          </td>

                          <td className="px-4 py-3">
                            {isMe ? (
                              // You can't change your own role — the backend blocks it too,
                              // but showing a picker only for the server to refuse is worse
                              // than not showing it at all.
                              <Badge tone={ROLES[u.role].tone} title="You can't change your own role">
                                {ROLES[u.role].label}
                              </Badge>
                            ) : (
                              <Select
                                value={u.role}
                                onValueChange={(v) => {
                                  if (v !== u.role) setPending({ kind: "role", user: u, newRole: v as Role });
                                }}
                                disabled={busy}
                              >
                                <SelectTrigger aria-label={`Role for ${u.display_name}`} className="h-8 w-36 justify-between">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {ROLE_ORDER.map((r) => (
                                    <SelectItem key={r} value={r} description={ROLES[r].description}>
                                      {ROLES[r].label}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            )}
                          </td>

                          <td className="px-4 py-3">
                            {u.is_active ? <Badge tone="success">Active</Badge> : <Badge tone="danger">Locked</Badge>}
                          </td>

                          <td className="px-4 py-3 text-[var(--muted-foreground)]">
                            <time dateTime={u.last_login_at ?? undefined} title={u.last_login_at ?? undefined}>
                              {lastLogin(u.last_login_at)}
                            </time>
                          </td>

                          <td className="px-4 py-3">
                            <div className="flex items-center justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                onClick={() => setEditTarget(u)}
                                aria-label={`Edit ${u.display_name}`}
                                title="Edit name"
                              >
                                <Pencil aria-hidden />
                              </Button>
                              {isMe ? (
                                // Resetting your own password is blocked by the backend (that
                                // route doesn't ask for the old password) — send to Account.
                                <Link href="/account" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                                  <KeyRound aria-hidden />
                                  Change password
                                </Link>
                              ) : (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  onClick={() => setResetTarget(u)}
                                  aria-label={`Reset password for ${u.display_name}`}
                                  title="Reset password"
                                >
                                  <KeyRound aria-hidden />
                                </Button>
                              )}
                              {!isMe &&
                                (u.is_active ? (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setPending({ kind: "lock", user: u })}
                                    disabled={busy}
                                    className="hover:text-[var(--destructive)]"
                                  >
                                    <Lock aria-hidden />
                                    Lock
                                  </Button>
                                ) : (
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    onClick={() => setPending({ kind: "unlock", user: u })}
                                    disabled={busy}
                                  >
                                    <LockOpen aria-hidden />
                                    Unlock
                                  </Button>
                                ))}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
              </tbody>
            </table>
          </div>

          {!isLoading && visible.length === 0 && (
            <EmptyState
              icon={SearchX}
              title="No matching accounts"
              description="Try a different search or clear the role filter."
              className="rounded-none border-0"
            >
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setQuery("");
                  setFilter("all");
                }}
              >
                Clear filters
              </Button>
            </EmptyState>
          )}
        </div>
      )}

      {/* Feedback after an action. aria-live so screen readers announce it. */}
      <div aria-live="polite" className="pointer-events-none fixed bottom-6 right-6 z-50">
        {toast && (
          <div
            className={cn(
              "k8s-fade-in pointer-events-auto max-w-sm rounded-lg border px-4 py-3 text-sm shadow-lg",
              toast.kind === "ok"
                ? "border-emerald-500/30 bg-[var(--background)] text-emerald-700 dark:text-emerald-400"
                : "border-[var(--destructive)]/40 bg-[var(--background)] text-[var(--destructive)]",
            )}
          >
            {toast.message}
          </div>
        )}
      </div>

      <CreateUserDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(u) => {
          setCreateOpen(false);
          setToast({ kind: "ok", message: `Created account ${u.email} (${ROLES[u.role].label}).` });
        }}
      />

      <EditUserDialog
        user={editTarget}
        onClose={() => setEditTarget(null)}
        onDone={(u) => {
          setEditTarget(null);
          setToast({ kind: "ok", message: `Saved. The name is now ${u.display_name}.` });
        }}
      />

      <ResetPasswordDialog
        user={resetTarget}
        onClose={() => setResetTarget(null)}
        onDone={(u) => {
          setResetTarget(null);
          setToast({
            kind: "ok",
            message: `Reset the password for ${u.display_name}. All of their sessions were signed out.`,
          });
        }}
      />

      <ConfirmDialog
        open={pending !== null}
        destructive={dialog.destructive}
        title={dialog.title}
        description={dialog.description}
        confirmLabel={busy ? "Working…" : dialog.confirmLabel}
        onConfirm={runPending}
        onCancel={() => setPending(null)}
      />
    </div>
  );
}

function describeDialog(p: PendingAction | null) {
  if (!p) return { title: "", description: "", confirmLabel: "Confirm", destructive: false };
  if (p.kind === "lock") {
    return {
      title: `Lock ${p.user.display_name}'s account?`,
      description:
        "They are signed out of every device right away and can't sign in again until unlocked. Their chat history is kept.",
      confirmLabel: "Lock account",
      destructive: true,
    };
  }
  if (p.kind === "unlock") {
    return {
      title: `Unlock ${p.user.display_name}?`,
      description: "They will be able to sign in again with their old password.",
      confirmLabel: "Unlock",
      destructive: false,
    };
  }
  const isPromotion = p.newRole === "admin";
  return {
    title: `Change ${p.user.display_name} to ${ROLES[p.newRole].label}?`,
    description: isPromotion
      ? "Admins can change system settings and create or lock other accounts — including yours. Only grant this to people who really need it."
      : `${ROLES[p.newRole].label}: ${ROLES[p.newRole].description.toLowerCase()}. The new permissions apply from their next request.`,
    confirmLabel: "Change role",
    destructive: isPromotion,
  };
}

function StatCard({
  label,
  value,
  icon: Icon,
  isLoading,
}: {
  label: string;
  value: number;
  icon: typeof Users;
  isLoading: boolean;
}) {
  return (
    <div className="rounded-lg border bg-[var(--card)] p-4">
      <div className="flex items-center justify-between text-xs font-medium text-[var(--muted-foreground)]">
        {label}
        <Icon aria-hidden className="size-4" />
      </div>
      {isLoading ? (
        <div className="mt-2 h-7 w-10 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
      ) : (
        <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      )}
    </div>
  );
}

function SkeletonRow() {
  return (
    <tr aria-hidden>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="size-8 animate-pulse rounded-full bg-[var(--muted)] motion-reduce:animate-none" />
          <div className="space-y-1.5">
            <div className="h-3.5 w-32 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
            <div className="h-3 w-44 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
          </div>
        </div>
      </td>
      {[36, 20, 28, 16].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-3.5 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" style={{ width: `${w * 4}px` }} />
        </td>
      ))}
    </tr>
  );
}
