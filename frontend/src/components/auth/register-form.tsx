"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { CircleAlert, Info } from "lucide-react";

import { AuthShell } from "@/components/auth/auth-shell";
import { Button } from "@/components/ui/button";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { useRegister } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";

/** Matches `password: str = Field(min_length=8, ...)` in backend/app/schemas/auth.py
 * — checked here first so users see the error right away, without waiting for the server. */
const MIN_PASSWORD_LENGTH = 8;

export function RegisterForm() {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const register = useRegister();
  const router = useRouter();

  const passwordTooShort = password.length > 0 && password.length < MIN_PASSWORD_LENGTH;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (passwordTooShort) return;
    register.mutate(
      { email: email.trim(), password, display_name: displayName.trim() },
      { onSuccess: () => router.replace("/chat") },
    );
  }

  return (
    <AuthShell>
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Create an account</h1>
        <p className="mt-1.5 text-sm text-[var(--muted-foreground)]">
          It only takes a minute. You can start asking questions right after signing up.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <Field id="display_name" label="Display name">
          <Input
            id="display_name"
            required
            autoFocus
            autoComplete="name"
            placeholder="Jane Doe"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            disabled={register.isPending}
          />
        </Field>

        <Field id="email" label="Email">
          <Input
            id="email"
            type="email"
            required
            autoComplete="username"
            placeholder="name@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={register.isPending}
          />
        </Field>

        <Field
          id="password"
          label="Password"
          error={passwordTooShort ? `Use at least ${MIN_PASSWORD_LENGTH} characters.` : null}
          hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
        >
          <PasswordInput
            id="password"
            required
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={register.isPending}
            aria-invalid={passwordTooShort}
            aria-describedby="password-description"
          />
        </Field>

        <div className="flex items-start gap-2 rounded-md bg-[var(--muted)] px-3 py-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
          <Info aria-hidden className="mt-0.5 size-3.5 shrink-0" />
          New accounts can ask questions and run existing skills. To administer the system or
          add/edit skills, ask an admin to upgrade your role.
        </div>

        {register.isError && (
          <div
            role="alert"
            className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
          >
            <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
            {register.error instanceof ApiError ? register.error.message : "Couldn't sign up. Try again."}
          </div>
        )}

        <Button type="submit" size="lg" className="w-full" disabled={register.isPending}>
          {register.isPending ? "Creating account…" : "Sign up"}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        Already have an account?{" "}
        <Link
          href="/login"
          className="rounded font-medium text-[var(--foreground)] underline underline-offset-4 outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          Sign in
        </Link>
      </p>
    </AuthShell>
  );
}
