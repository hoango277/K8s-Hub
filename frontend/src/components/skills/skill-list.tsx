"use client";

import { useMemo, useState } from "react";
import { BookOpen, FileArchive, Plus, Search, SearchX } from "lucide-react";

import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { ImportSkillDialog } from "@/components/skills/import-skill-dialog";
import { SkillCard } from "@/components/skills/skill-card";
import { ErrorPanel, SectionHeader, errorMessage } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { inputClass } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useSetSkillEnabled, useSkills } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";

/** The Skills section: the catalog plus the create/import actions for engineers. */
export function SkillList({ canEdit, description }: { canEdit: boolean; description: string }) {
  const { data: skills, isLoading, error, refetch } = useSkills();
  const setEnabled = useSetSkillEnabled();
  const toast = useToast();

  const [query, setQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [importOpen, setImportOpen] = useState(false);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = skills ?? [];
    if (!q) return list;
    return list.filter((s) => s.name.includes(q) || s.description.toLowerCase().includes(q));
  }, [skills, query]);

  function toggle(name: string, enabled: boolean) {
    setEnabled.mutate(
      { name, enabled },
      {
        onSuccess: () =>
          toast({
            kind: "ok",
            message: enabled ? `${name} is enabled — the assistant can use it.` : `${name} is disabled.`,
          }),
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't update ${name}. Try again.`) }),
      },
    );
  }

  const actions = canEdit ? (
    <>
      <Button variant="outline" onClick={() => setImportOpen(true)}>
        <FileArchive aria-hidden />
        Import .zip
      </Button>
      <Button onClick={() => setCreateOpen(true)}>
        <Plus aria-hidden />
        New skill
      </Button>
    </>
  ) : null;

  return (
    <>
      <SectionHeader title="Skills" description={description} actions={actions} />

      {isLoading ? (
        <ul aria-label="Loading skills" className="grid gap-3 sm:grid-cols-2">
          {Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="h-40 rounded-lg border p-4">
              <div className="h-4 w-2/5 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
              <div className="mt-3 h-3 w-1/5 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
              <div className="mt-5 h-3 w-full animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
              <div className="mt-2 h-3 w-4/5 animate-pulse rounded bg-[var(--muted)] motion-reduce:animate-none" />
            </li>
          ))}
        </ul>
      ) : error ? (
        <ErrorPanel title="Couldn't load skills" error={error} onRetry={() => void refetch()} />
      ) : !skills || skills.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title="No skills yet"
          description={
            canEdit
              ? "A skill is a SKILL.md with a name, a description of when to use it, and step-by-step instructions. Create one here or import a skill folder as a .zip."
              : "A skill teaches the assistant how to handle a kind of task. Ask an engineer to add one — it will show up here."
          }
        >
          {canEdit && (
            <>
              <Button variant="outline" size="sm" onClick={() => setImportOpen(true)}>
                <FileArchive aria-hidden />
                Import .zip
              </Button>
              <Button size="sm" onClick={() => setCreateOpen(true)}>
                <Plus aria-hidden />
                New skill
              </Button>
            </>
          )}
        </EmptyState>
      ) : (
        <>
          <div className="relative mb-4 w-full sm:w-72">
            <Search
              aria-hidden
              className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--muted-foreground)]"
            />
            <label htmlFor="skill-search" className="sr-only">
              Search skills
            </label>
            <input
              id="skill-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by name or description…"
              className={cn(inputClass, "pl-9")}
            />
          </div>

          {visible.length === 0 ? (
            <EmptyState
              icon={SearchX}
              title="No matching skills"
              description={`Nothing matches “${query.trim()}”. Try another word, or clear the search.`}
            >
              <Button variant="outline" size="sm" onClick={() => setQuery("")}>
                Clear search
              </Button>
            </EmptyState>
          ) : (
            <ul className="grid gap-3 sm:grid-cols-2">
              {visible.map((s) => (
                <SkillCard
                  key={s.name}
                  skill={s}
                  canEdit={canEdit}
                  pending={setEnabled.isPending && setEnabled.variables?.name === s.name}
                  onToggle={(enabled) => toggle(s.name, enabled)}
                />
              ))}
            </ul>
          )}
        </>
      )}

      {canEdit && (
        <>
          <CreateSkillDialog
            open={createOpen}
            onClose={() => setCreateOpen(false)}
            existing={(skills ?? []).map((s) => s.name)}
          />
          <ImportSkillDialog open={importOpen} onClose={() => setImportOpen(false)} />
        </>
      )}
    </>
  );
}
