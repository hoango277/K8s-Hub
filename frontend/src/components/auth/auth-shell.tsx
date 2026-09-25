import { Boxes, MessagesSquare, ShieldCheck, Stethoscope } from "lucide-react";

/**
 * Shared frame for the login and register pages: a product intro column on
 * the left (hidden on narrow screens), the form on the right. First-time
 * visitors understand what the system is for before having to create an
 * account.
 */
const HIGHLIGHTS = [
  {
    icon: MessagesSquare,
    title: "Operate in plain language",
    description: "Ask about your cluster; the assistant looks things up and explains.",
  },
  {
    icon: Stethoscope,
    title: "Diagnose incidents",
    description: "Gather events, logs and metrics to find the root cause.",
  },
  {
    icon: ShieldCheck,
    title: "Every change is approved",
    description: "Dry-run, review the diff, and get approval before anything is applied.",
  },
];

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[1fr_1.1fr]">
      <aside className="relative hidden overflow-hidden border-r bg-[var(--muted)]/40 p-10 lg:flex lg:flex-col">
        {/* Faint grid pattern in the background — purely decorative, hidden from screen readers. */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 opacity-[0.35] [background-image:linear-gradient(var(--border)_1px,transparent_1px),linear-gradient(90deg,var(--border)_1px,transparent_1px)] [background-size:32px_32px] [mask-image:radial-gradient(ellipse_at_top_left,black,transparent_70%)]"
        />

        <div className="relative flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] shadow-sm">
            <Boxes aria-hidden className="size-5" />
          </span>
          <span className="text-lg font-semibold tracking-tight">K8s Hub</span>
        </div>

        <div className="relative mt-auto max-w-md">
          <h2 className="text-3xl font-semibold leading-tight tracking-tight text-balance">
            Run Kubernetes with an AI assistant
          </h2>
          <p className="mt-3 text-sm leading-relaxed text-[var(--muted-foreground)]">
            One place to ask, diagnose and act on your cluster — safe, controlled and fully
            audited.
          </p>

          <ul className="mt-8 space-y-5">
            {HIGHLIGHTS.map(({ icon: Icon, title, description }) => (
              <li key={title} className="flex gap-3">
                <span className="flex size-9 shrink-0 items-center justify-center rounded-lg border bg-[var(--background)]">
                  <Icon aria-hidden className="size-4" />
                </span>
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="text-sm text-[var(--muted-foreground)]">{description}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <main className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          {/* Logo for narrow screens, where the left column is hidden. */}
          <div className="mb-8 flex items-center justify-center gap-2 lg:hidden">
            <span className="flex size-8 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)]">
              <Boxes aria-hidden className="size-4" />
            </span>
            <span className="font-semibold tracking-tight">K8s Hub</span>
          </div>
          {children}
        </div>
      </main>
    </div>
  );
}
