"use client";

import Link from "next/link";
import { ShieldX } from "lucide-react";

import { buttonVariants } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { useCurrentUser } from "@/hooks/use-auth";
import { ROLES, hasRole } from "@/lib/roles";
import type { Role } from "@/types/auth";

/**
 * Only shows content to allowed roles.
 *
 * The sidebar already hides these pages from other roles, but users can still
 * type the URL directly. In that case show a page that explains clearly,
 * instead of letting them see the form and then get a 403 when they save.
 *
 * This is a DISPLAY layer. Real permissions are still enforced by the backend
 * (`require_role`).
 */
export function RoleGate({ allow, children }: { allow: Role[]; children: React.ReactNode }) {
  const { data: user } = useCurrentUser();

  // AuthGate in the layout already guarantees a user before we get here.
  if (!user) return null;

  if (!hasRole(user.role, allow)) {
    const required = allow.map((r) => ROLES[r].label).join(" or ");
    return (
      <div className="mx-auto max-w-2xl px-6 pt-16">
        <EmptyState
          icon={ShieldX}
          title="You don't have access to this page"
          description={
            <>
              This page is for the <strong className="text-[var(--foreground)]">{required}</strong> role.
              Your account is {ROLES[user.role].label}. If you need access, contact an admin.
            </>
          }
        >
          <Link href="/chat" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to Chat
          </Link>
        </EmptyState>
      </div>
    );
  }

  return <>{children}</>;
}
