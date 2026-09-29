"use client";

import Link from "next/link";
import { FileText } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { SkillSummary } from "@/types/skill";

export function SourceBadge({ source }: { source: SkillSummary["source"] }) {
  return source === "builtin" ? <Badge tone="neutral">Built-in</Badge> : <Badge tone="violet">Custom</Badge>;
}

/** One skill in the catalog. The name is the link; the switch sits outside
 * it, so toggling never navigates away by accident. */
export function SkillCard({
  skill,
  canEdit,
  pending,
  onToggle,
}: {
  skill: SkillSummary;
  canEdit: boolean;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
}) {
  const labelId = `skill-${skill.name}-name`;
  return (
    <li
      className={cn(
        "relative flex min-w-0 flex-col rounded-lg border p-4 transition hover:border-[var(--ring)]",
        "has-[a:focus-visible]:ring-2 has-[a:focus-visible]:ring-[var(--ring)]",
        !skill.enabled && "bg-[var(--muted)]/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="min-w-0">
            {/* The ::after stretches the link over the whole card, so any
                click on it opens the skill; the switch sits above it (z-10). */}
            <Link
              id={labelId}
              href={`/skills/${encodeURIComponent(skill.name)}`}
              className="break-all font-mono text-sm font-semibold outline-none after:absolute after:inset-0 after:rounded-lg hover:underline"
            >
              {skill.name}
            </Link>
          </h3>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <SourceBadge source={skill.source} />
            {!skill.enabled && <Badge tone="warning">Disabled</Badge>}
          </div>
        </div>
        {canEdit && (
          <Switch
            className="z-10"
            checked={skill.enabled}
            pending={pending}
            onCheckedChange={onToggle}
            aria-label={`${skill.enabled ? "Disable" : "Enable"} ${skill.name}`}
          />
        )}
      </div>
      <p className="mt-3 line-clamp-3 text-sm leading-relaxed text-[var(--muted-foreground)]">{skill.description}</p>
      <p className="mt-auto flex items-center gap-1.5 pt-3 text-xs text-[var(--muted-foreground)]">
        <FileText aria-hidden className="size-3.5" />
        {skill.files.length} {skill.files.length === 1 ? "file" : "files"}
      </p>
    </li>
  );
}
