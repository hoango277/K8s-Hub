"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LogOut } from "lucide-react";

import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useCurrentUser, useLogout } from "@/hooks/use-auth";
import { ROLES } from "@/lib/roles";
import { cn } from "@/lib/utils";

/** Top bar of every page in (app) — who is signed in (click to open the
 * Account page, where the password is changed), their role, and a sign-out
 * button. */
export function Header() {
  const { data: user } = useCurrentUser();
  const logout = useLogout();
  const pathname = usePathname();

  if (!user) return null;

  return (
    <header className="flex h-12 shrink-0 items-center justify-end gap-3 border-b px-4">
      <Link
        href="/account"
        title="My account"
        aria-current={pathname === "/account" ? "page" : undefined}
        className={cn(
          "flex min-w-0 items-center gap-2.5 rounded-md px-2 py-1 outline-none transition",
          "hover:bg-[var(--accent)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
          pathname === "/account" && "bg-[var(--accent)]",
        )}
      >
        <Avatar name={user.display_name} className="size-7 text-[11px]" />
        <span className="hidden min-w-0 leading-tight sm:block">
          <span className="block truncate text-sm font-medium">{user.display_name}</span>
          <span className="block truncate text-xs text-[var(--muted-foreground)]">{user.email}</span>
        </span>
        <Badge tone={ROLES[user.role].tone}>{ROLES[user.role].label}</Badge>
      </Link>

      <div aria-hidden className="h-5 w-px bg-[var(--border)]" />

      <Button variant="ghost" size="sm" onClick={() => logout.mutate()} disabled={logout.isPending}>
        <LogOut aria-hidden />
        {logout.isPending ? "Signing out…" : "Sign out"}
      </Button>
    </header>
  );
}
