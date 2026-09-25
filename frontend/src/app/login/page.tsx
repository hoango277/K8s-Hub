import { Suspense } from "react";

import { LoginForm } from "@/components/auth/login-form";

export const metadata = { title: "Sign in · K8s Hub" };

export default function LoginPage() {
  return (
    // useSearchParams() in LoginForm needs a Suspense boundary for static
    // rendering — without it, the build fails instead of just warning.
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
