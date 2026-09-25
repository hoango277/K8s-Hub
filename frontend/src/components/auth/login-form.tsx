"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { CircleAlert } from "lucide-react";

import { AuthShell } from "@/components/auth/auth-shell";
import { Button } from "@/components/ui/button";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { useLogin } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";

export function LoginForm() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const login = useLogin();
  const router = useRouter();
  const params = useSearchParams();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    login.mutate(
      { email: email.trim(), password },
      {
        // `next` is attached by AuthGate when it bounces a signed-out page
        // here — return to where the user was headed, instead of always /chat.
        onSuccess: () => router.replace(params.get("next") || "/chat"),
      },
    );
  }

  return (
    <AuthShell>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1.5 text-sm text-[var(--muted-foreground)]">
          Welcome back. Enter your email and password to continue.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <Field id="email" label="Email">
          <Input
            id="email"
            type="email"
            required
            autoFocus
            autoComplete="username"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={login.isPending}
          />
        </Field>

        <Field id="password" label="Password">
          <PasswordInput
            id="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={login.isPending}
          />
        </Field>

        {login.isError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
          >
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {login.error instanceof ApiError
              ? login.error.message
              : "Couldn't sign in. Try again."}
          </div>
        )}

        <Button type="submit" size="lg" className="w-full" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        Don&apos;t have an account?{" "}
        <Link
          href="/register"
          className="rounded font-medium text-[var(--foreground)] underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          Sign up
        </Link>
      </p>
    </AuthShell>
  );
}
