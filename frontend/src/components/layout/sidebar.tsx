"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Boxes,
  ClipboardCheck,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Stethoscope,
  Telescope,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { useCurrentUser } from "@/hooks/use-auth";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { hasRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { Role } from "@/types/auth";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Omit for all roles. When set, only the listed roles see it. */
  roles?: Role[];
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

// Hide entirely what the current role can't use, rather than letting them
// click and get a 403 — see the UI/UX guidelines in CLAUDE.md. Real
// permissions are enforced by `require_role` on the backend; this is only the
// display layer.
const GROUPS: NavGroup[] = [
  {
    title: "Operations",
    items: [
      { href: "/chat", label: "Chat", icon: MessagesSquare },
      { href: "/rca", label: "Diagnosis", icon: Stethoscope },
      { href: "/skills", label: "Skills", icon: Wrench },
      { href: "/approvals", label: "Approvals", icon: ClipboardCheck },
      { href: "/observability", label: "AI observability", icon: Telescope },
    ],
  },
  {
    title: "Administration",
    items: [
      { href: "/users", label: "Users", icon: Users, roles: ["admin"] },
      { href: "/settings", label: "Settings", icon: Settings, roles: ["admin"] },
    ],
  },
];

const COLLAPSED_KEY = "k8shub.nav";

export function Sidebar() {
  const pathname = usePathname();
  const { data: user } = useCurrentUser();

  const [stored, saveCollapsed] = useLocalStorage(COLLAPSED_KEY);
  const collapsed = stored === "1";

  const visibleGroups = GROUPS.map((g) => ({
    ...g,
    items: g.items.filter((m) => !m.roles || (user && hasRole(user.role, m.roles))),
  })).filter((g) => g.items.length > 0);

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r bg-[var(--muted)]/30 transition-[width] duration-200 ease-out motion-reduce:transition-none",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <div className={cn("flex h-12 items-center gap-2 border-b px-2", collapsed && "justify-center")}>
        {!collapsed && (
          <Link
            href="/chat"
            className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 py-1 outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-[var(--primary)] text-[var(--primary-foreground)]">
              <Boxes aria-hidden className="size-4" />
            </span>
            <span className="truncate text-sm font-semibold tracking-tight">K8s Hub</span>
          </Link>
        )}

        <button
          type="button"
          onClick={() => saveCollapsed(collapsed ? "0" : "1")}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand" : "Collapse"}
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-md outline-none transition",
            "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
            "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
          )}
        >
          {collapsed ? <PanelLeftOpen aria-hidden className="size-4" /> : <PanelLeftClose aria-hidden className="size-4" />}
        </button>
      </div>

      <nav aria-label="Main navigation" className="flex flex-1 flex-col gap-5 overflow-y-auto px-2 py-3">
        {visibleGroups.map((group) => (
          <div key={group.title}>
            {collapsed ? (
              <div aria-hidden className="mx-2 mb-2 border-t first:hidden" />
            ) : (
              <p className="mb-1 px-2.5 text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
                {group.title}
              </p>
            )}
            <ul className="flex flex-col gap-0.5">
              {group.items.map((m) => {
                const isActive = pathname === m.href || pathname.startsWith(`${m.href}/`);
                const Icon = m.icon;
                return (
                  <li key={m.href}>
                    <Link
                      href={m.href}
                      // When collapsed the text disappears, leaving only the
                      // icon — `title` and `aria-label` are all that's left to
                      // tell which link is which.
                      title={collapsed ? m.label : undefined}
                      aria-label={collapsed ? m.label : undefined}
                      aria-current={isActive ? "page" : undefined}
                      className={cn(
                        "relative flex h-9 items-center gap-2.5 rounded-md text-sm outline-none transition",
                        "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                        collapsed ? "justify-center px-0" : "px-2.5",
                        isActive
                          ? "bg-[var(--accent)] font-medium text-[var(--accent-foreground)]"
                          : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/60 hover:text-[var(--foreground)]",
                      )}
                    >
                      {/* Marker bar for the active item. When collapsed, the light
                          gray background isn't clear enough on a small square, so
                          this extra marker is needed. */}
                      {isActive && (
                        <span aria-hidden className="absolute left-0 h-5 w-0.5 rounded-r bg-[var(--primary)]" />
                      )}
                      <Icon aria-hidden className="size-4 shrink-0" />
                      {!collapsed && <span className="truncate">{m.label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}
