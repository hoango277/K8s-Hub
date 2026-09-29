"use client";

import { useSyncExternalStore } from "react";
import { BookOpen, History, Plug, Wrench, type LucideIcon } from "lucide-react";

import { McpServersPanel } from "@/components/skills/mcp-servers-panel";
import { RunHistoryPanel } from "@/components/skills/run-history-panel";
import { SkillList } from "@/components/skills/skill-list";
import { ToolsPanel } from "@/components/skills/tools-panel";
import { PageHeader } from "@/components/ui/page-header";
import { useCurrentUser } from "@/hooks/use-auth";
import { hasRole } from "@/lib/roles";
import { cn } from "@/lib/utils";

type SectionId = "skills" | "tools" | "mcp" | "history";

interface Section {
  id: SectionId;
  label: string;
  icon: LucideIcon;
  description: string;
}

const SECTIONS: Section[] = [
  {
    id: "skills",
    label: "Skills",
    icon: BookOpen,
    description:
      "Instructions the assistant loads when a task matches: a SKILL.md, plus optional scripts, references and assets.",
  },
  {
    id: "tools",
    label: "Tools",
    icon: Wrench,
    description:
      "Code the assistant can call — built-in Kubernetes, metrics, logs and trace tools, plus tools from MCP servers.",
  },
  {
    id: "mcp",
    label: "MCP servers",
    icon: Plug,
    description: "External servers that add their own tools to the catalog over the Model Context Protocol.",
  },
  {
    id: "history",
    label: "Run history",
    icon: History,
    description: "Every skill script and tool run, from the chat or started by hand here — newest first.",
  },
];

// Same approach as the Settings page: the open section lives in the URL hash
// so it survives a reload and works with the back button, read through
// useSyncExternalStore so the server render doesn't touch `location`.
function subscribeHash(onChange: () => void) {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function useSectionFromHash(): SectionId {
  const hash = useSyncExternalStore(
    subscribeHash,
    () => window.location.hash.slice(1),
    () => "",
  );
  return SECTIONS.some((s) => s.id === hash) ? (hash as SectionId) : "skills";
}

export function SkillsPage() {
  const { data: user } = useCurrentUser();
  // Only decides what to SHOW — the backend enforces the same rule.
  const canEdit = user ? hasRole(user.role, ["engineer"]) : false;

  const current = useSectionFromHash();
  const section = SECTIONS.find((s) => s.id === current)!;

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:px-6">
      <PageHeader
        icon={BookOpen}
        title="Skills"
        description="Skills teach the assistant how to handle a kind of task; tools are what it calls to do the work. Manage both here."
      />

      <div className="grid gap-8 md:grid-cols-[13rem_minmax(0,1fr)]">
        {/* A column on desktop, a scrollable row on phones. min-w-0 so the
            row scrolls instead of widening the grid column. */}
        <nav aria-label="Skills sections" className="min-w-0 md:sticky md:top-6 md:self-start">
          <ul className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1 md:flex-col md:overflow-visible">
            {SECTIONS.map((s) => {
              const active = s.id === section.id;
              return (
                <li key={s.id} className="shrink-0">
                  <a
                    href={`#${s.id}`}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm outline-none transition",
                      "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                      active
                        ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                        : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/60 hover:text-[var(--foreground)]",
                    )}
                  >
                    <s.icon aria-hidden className="size-4 shrink-0" />
                    {s.label}
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>

        <section aria-labelledby="section-title" className="min-w-0">
          {section.id === "skills" && <SkillList canEdit={canEdit} description={section.description} />}
          {section.id === "tools" && <ToolsPanel canEdit={canEdit} description={section.description} />}
          {section.id === "mcp" && <McpServersPanel canEdit={canEdit} description={section.description} />}
          {section.id === "history" && <RunHistoryPanel description={section.description} />}
        </section>
      </div>
    </div>
  );
}
