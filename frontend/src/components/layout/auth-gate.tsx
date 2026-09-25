"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Boxes, CloudOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { isUnauthorizedError, useHasSession, useCurrentUser } from "@/hooks/use-auth";
import { hasSession } from "@/lib/auth-tokens";

/**
 * Blocks every page under `(app)/` until we've confirmed the user is signed in.
 *
 * The check lives HERE (one place, wrapping the whole layout) instead of each
 * page checking for itself — one page forgetting the check is one hole that
 * lets people in without signing in, and that kind of bug only shows up when
 * someone happens to type the right URL.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const sessionExists = useHasSession();
  const { data: user, error, refetch, isFetching } = useCurrentUser();
  const sessionExpired = isUnauthorizedError(error);
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    // Read localStorage DIRECTLY (`hasSession()`), not `sessionExists`.
    //
    // During hydration, `useSyncExternalStore` always returns the server
    // snapshot — i.e. "no session" — before re-rendering with the real value.
    // This effect runs right at that first commit. Relying on `sessionExists`
    // meant EVERY page reload (F5) kicked the user back to /login even though
    // the session was intact: this actually happened and was only caught by
    // taking screenshots in a real browser.
    if (!hasSession() || sessionExpired) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [sessionExists, sessionExpired, pathname, router]);

  if (sessionExists && user) return <>{children}</>;

  // An error that is NOT a 401 (backend down, network lost): the session is
  // still there, don't kick the user to /login — they'd think they were
  // signed out. Say so clearly and offer a retry.
  if (error && !sessionExpired) {
    return (
      <div className="flex h-screen flex-col items-center justify-center gap-3 px-6 text-center">
        <span className="flex size-10 items-center justify-center rounded-lg bg-[var(--accent)]">
          <CloudOff aria-hidden className="size-5 text-[var(--muted-foreground)]" />
        </span>
        <p className="text-sm font-medium">Can&apos;t reach the server</p>
        <p className="max-w-sm text-sm text-[var(--muted-foreground)]">
          You&apos;re still signed in. Check that the backend is running, then try again.
        </p>
        <Button variant="outline" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          {isFetching ? "Retrying…" : "Try again"}
        </Button>
      </div>
    );
  }

  // Everything else shows a waiting screen: hydrating, asking /auth/me, or
  // redirecting to /login. Don't return `null` — a blank frame looks like a
  // bug. This screen holds no data, so pre-rendering it on the server leaks
  // nothing.
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-4">
      <span className="flex size-10 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)]">
        <Boxes aria-hidden className="size-5" />
      </span>
      <div className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
        <Spinner label="Checking your session" />
        Checking your session…
      </div>
    </div>
  );
}
