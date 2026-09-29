"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BookOpen,
  Download,
  FileCode,
  FilePlus,
  FileSearch,
  FileText,
  Folder,
  Info,
  Trash2,
} from "lucide-react";

import { AddFileDialog } from "@/components/skills/add-file-dialog";
import { SkillRunList } from "@/components/skills/execution-log";
import { FileView } from "@/components/skills/file-view";
import { ErrorPanel, errorMessage, formatBytes } from "@/components/skills/shared";
import { SourceBadge } from "@/components/skills/skill-card";
import { SkillRunForm } from "@/components/skills/skill-run-form";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useCurrentUser } from "@/hooks/use-auth";
import {
  useDeleteSkill,
  useDeleteSkillFile,
  useExportSkill,
  useSetSkillEnabled,
  useSkill,
} from "@/hooks/use-skills";
import { ApiError } from "@/lib/api";
import { hasRole } from "@/lib/roles";
import { cn } from "@/lib/utils";
import type { SkillFile } from "@/types/skill";

const SKILL_FILE = "SKILL.md";

// ---------------------------------------------------------------------------
// File tree: SKILL.md first, then the standard folders in the order the
// Agent Skills layout describes them, then anything else.
// ---------------------------------------------------------------------------

interface Group {
  folder: string | null;
  files: SkillFile[];
}

const FOLDER_ORDER = ["scripts/", "references/", "assets/"];

function groupFiles(files: SkillFile[]): Group[] {
  const root: SkillFile[] = [];
  const byFolder = new Map<string, SkillFile[]>();
  for (const f of files) {
    const slash = f.path.indexOf("/");
    if (slash === -1) root.push(f);
    else {
      const folder = f.path.slice(0, slash + 1);
      byFolder.set(folder, [...(byFolder.get(folder) ?? []), f]);
    }
  }
  root.sort((a, b) => (a.path === SKILL_FILE ? -1 : b.path === SKILL_FILE ? 1 : a.path.localeCompare(b.path)));
  const folders = [...byFolder.keys()].sort((a, b) => {
    const ia = FOLDER_ORDER.indexOf(a);
    const ib = FOLDER_ORDER.indexOf(b);
    return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
  });
  return [
    { folder: null, files: root },
    ...folders.map((folder) => ({
      folder,
      files: byFolder.get(folder)!.sort((a, b) => a.path.localeCompare(b.path)),
    })),
  ];
}

function fileIcon(path: string) {
  if (path.startsWith("scripts/")) return FileCode;
  if (path.startsWith("references/")) return FileSearch;
  return FileText;
}

export function SkillDetail({ name }: { name: string }) {
  const router = useRouter();
  const toast = useToast();
  const { data: user } = useCurrentUser();
  const { data: skill, isLoading, error, refetch } = useSkill(name);
  const setEnabled = useSetSkillEnabled();
  const exportZip = useExportSkill();
  const removeSkill = useDeleteSkill();
  const removeFile = useDeleteSkillFile();

  const canEdit = user ? hasRole(user.role, ["engineer"]) : false;
  const editable = canEdit && skill?.source === "custom";

  const [selected, setSelected] = useState(SKILL_FILE);
  const [dirty, setDirty] = useState(false);
  // A file the user clicked while the open one has unsaved edits.
  const [switchTo, setSwitchTo] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [deleteFile, setDeleteFile] = useState<string | null>(null);
  const [deleteSkill, setDeleteSkill] = useState(false);

  // Closing or reloading the tab with unsaved edits asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const files = useMemo(() => skill?.files ?? [], [skill]);
  const groups = useMemo(() => groupFiles(files), [files]);
  // Fall back to SKILL.md when the selected file was just deleted.
  const current = files.find((f) => f.path === selected) ?? files.find((f) => f.path === SKILL_FILE) ?? null;

  function select(path: string) {
    if (path === current?.path) return;
    if (dirty) setSwitchTo(path);
    else setSelected(path);
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 p-16 text-sm text-[var(--muted-foreground)]">
        <Spinner /> Loading skill…
      </div>
    );
  }

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="mx-auto max-w-2xl px-4 pt-16 sm:px-6">
        <EmptyState
          icon={BookOpen}
          title="Skill not found"
          description={
            <>
              There&apos;s no skill named <code>{name}</code>. It may have been deleted or renamed in an import.
            </>
          }
        >
          <Link href="/skills" className={buttonVariants({ variant: "outline", size: "sm" })}>
            Back to Skills
          </Link>
        </EmptyState>
      </div>
    );
  }

  if (error || !skill) {
    return (
      <div className="mx-auto max-w-6xl px-4 pt-8 sm:px-6">
        <ErrorPanel title="Couldn't load this skill" error={error} onRetry={() => void refetch()} />
      </div>
    );
  }

  function toggleEnabled(enabled: boolean) {
    setEnabled.mutate(
      { name, enabled },
      {
        onSuccess: () =>
          toast({ kind: "ok", message: enabled ? `${name} is enabled — the assistant can use it.` : `${name} is disabled.` }),
        onError: (err) => toast({ kind: "error", message: errorMessage(err, "Couldn't update the skill. Try again.") }),
      },
    );
  }

  function download() {
    exportZip.mutate(name, {
      onSuccess: () => toast({ kind: "ok", message: `Downloaded ${name}.zip.` }),
      onError: (err) => toast({ kind: "error", message: errorMessage(err, "Couldn't export the skill. Try again.") }),
    });
  }

  function confirmDeleteFile() {
    if (!deleteFile) return;
    const path = deleteFile;
    removeFile.mutate(
      { name, path },
      {
        onSuccess: () => toast({ kind: "ok", message: `Deleted ${path}.` }),
        onError: (err) => toast({ kind: "error", message: errorMessage(err, `Couldn't delete ${path}. Try again.`) }),
        onSettled: () => setDeleteFile(null),
      },
    );
  }

  function confirmDeleteSkill() {
    removeSkill.mutate(name, {
      onSuccess: () => {
        toast({ kind: "ok", message: `Deleted the skill ${name}.` });
        setDirty(false);
        router.push("/skills");
      },
      onError: (err) => {
        toast({ kind: "error", message: errorMessage(err, "Couldn't delete the skill. Try again.") });
        setDeleteSkill(false);
      },
    });
  }

  const scripts = files.filter((f) => f.path.startsWith("scripts/"));

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-6 sm:px-6">
      <Link
        href="/skills"
        className="mb-4 inline-flex items-center gap-1.5 rounded-md text-sm text-[var(--muted-foreground)] outline-none hover:text-[var(--foreground)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        <ArrowLeft aria-hidden className="size-4" />
        All skills
      </Link>

      <PageHeader
        icon={BookOpen}
        title={skill.name}
        description={skill.description}
        className="mb-4"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canEdit && (
              <span className="mr-1 flex items-center gap-2">
                <span id="skill-enabled-label" className="text-sm text-[var(--muted-foreground)]">
                  Enabled
                </span>
                <Switch
                  checked={skill.enabled}
                  pending={setEnabled.isPending}
                  onCheckedChange={toggleEnabled}
                  aria-labelledby="skill-enabled-label"
                />
              </span>
            )}
            <Button variant="outline" onClick={download} disabled={exportZip.isPending}>
              {exportZip.isPending ? <Spinner label="Exporting" /> : <Download aria-hidden />}
              Export .zip
            </Button>
            {editable && (
              <Button variant="destructive" onClick={() => setDeleteSkill(true)}>
                <Trash2 aria-hidden />
                Delete
              </Button>
            )}
          </div>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-1.5">
        <SourceBadge source={skill.source} />
        {skill.enabled ? <Badge tone="success">Enabled</Badge> : <Badge tone="warning">Disabled</Badge>}
        <Badge tone="neutral">
          {files.length} {files.length === 1 ? "file" : "files"}
        </Badge>
        {scripts.length > 0 && (
          <Badge tone="info">
            {scripts.length} {scripts.length === 1 ? "script" : "scripts"}
          </Badge>
        )}
      </div>

      {skill.source === "builtin" && (
        <p
          role="note"
          className="mb-6 flex items-start gap-2 rounded-md border bg-[var(--muted)]/50 px-3 py-2.5 text-sm leading-relaxed text-[var(--muted-foreground)]"
        >
          <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
          Built-in skills are part of the code — export and import a copy to customise it.
        </p>
      )}

      <div className="grid gap-6 md:grid-cols-[15rem_minmax(0,1fr)]">
        {/* File tree */}
        <nav aria-label="Skill files" className="min-w-0 md:sticky md:top-6 md:self-start">
          <div className="rounded-lg border">
            <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
              <h2 className="text-xs font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Files</h2>
              {editable && (
                <Button variant="ghost" size="sm" className="-mr-1 h-7 px-2" onClick={() => setAddOpen(true)}>
                  <FilePlus aria-hidden />
                  Add file
                </Button>
              )}
            </div>
            <div className="max-h-80 overflow-y-auto p-1.5 md:max-h-[calc(100dvh-12rem)]">
              {groups.map((g) =>
                g.files.length === 0 ? null : (
                  <div key={g.folder ?? "root"} className="mb-1 last:mb-0">
                    {g.folder && (
                      <p className="flex items-center gap-1.5 px-2 pb-1 pt-2 font-mono text-[11px] text-[var(--muted-foreground)]">
                        <Folder aria-hidden className="size-3.5" />
                        {g.folder}
                      </p>
                    )}
                    <ul>
                      {g.files.map((f) => {
                        const Icon = fileIcon(f.path);
                        const active = f.path === current?.path;
                        return (
                          <li key={f.path}>
                            <button
                              type="button"
                              onClick={() => select(f.path)}
                              aria-current={active ? "true" : undefined}
                              className={cn(
                                "flex min-h-8 w-full items-center gap-2 rounded-md px-2 py-1 text-left text-sm outline-none transition",
                                "focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                                g.folder && "pl-5",
                                active
                                  ? "bg-[var(--accent)] font-medium text-[var(--foreground)]"
                                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/60 hover:text-[var(--foreground)]",
                              )}
                            >
                              <Icon aria-hidden className="size-3.5 shrink-0" />
                              <span className="min-w-0 flex-1 truncate font-mono text-xs" title={f.path}>
                                {g.folder ? f.path.slice(g.folder.length) : f.path}
                              </span>
                              <span className="shrink-0 text-[10px] tabular-nums text-[var(--muted-foreground)]">
                                {formatBytes(f.size)}
                              </span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ),
              )}
            </div>
          </div>
          {editable && files.length === 1 && (
            <p className="mt-2 px-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
              Only SKILL.md so far. Add scripts the assistant can run, or reference documents it reads when needed.
            </p>
          )}
        </nav>

        {/* Selected file */}
        <div className="min-w-0 space-y-6">
          {current ? (
            <FileView
              // Siblings of SkillRunForm below, keyed by the same path: prefix both
              // so React never sees two children with one key.
              key={`file:${current.path}`}
              skill={name}
              path={current.path}
              size={current.size}
              editable={editable}
              frontmatter={current.path === SKILL_FILE ? skill.frontmatter : null}
              onDirtyChange={setDirty}
              onDelete={editable && current.path !== SKILL_FILE ? () => setDeleteFile(current.path) : null}
            />
          ) : (
            <EmptyState icon={FileText} title="No files" description="This skill has no SKILL.md, which shouldn't happen. Try reloading." />
          )}

          {canEdit && current?.path.startsWith("scripts/") && (
            <SkillRunForm key={`run:${current.path}`} skill={name} script={current.path} />
          )}
        </div>
      </div>

      <section aria-labelledby="recent-runs-title" className="mt-10">
        <h2 id="recent-runs-title" className="mb-3 text-lg font-semibold">
          Recent runs
        </h2>
        <SkillRunList
          skill={name}
          emptyHint={
            scripts.length === 0
              ? "This skill has no scripts, so there's nothing to run. Runs appear here once it has files under scripts/."
              : canEdit
                ? "Open a file under scripts/ and use “Run script”, or let the assistant run it from chat."
                : "Runs appear here when the assistant runs one of this skill's scripts from chat."
          }
        />
      </section>

      {editable && (
        <AddFileDialog
          open={addOpen}
          skill={name}
          existing={files.map((f) => f.path)}
          onClose={() => setAddOpen(false)}
          onCreated={(path) => {
            setDirty(false);
            setSelected(path);
          }}
        />
      )}

      <ConfirmDialog
        open={switchTo !== null}
        destructive
        title="Discard your changes?"
        description={`Your edits to ${current?.path ?? "this file"} haven't been saved and will be lost if you open another file.`}
        confirmLabel="Discard and open"
        cancelLabel="Keep editing"
        onConfirm={() => {
          if (switchTo) setSelected(switchTo);
          setSwitchTo(null);
        }}
        onCancel={() => setSwitchTo(null)}
      />

      <ConfirmDialog
        open={deleteFile !== null}
        destructive
        title={`Delete ${deleteFile ?? "this file"}?`}
        description="The file is removed from the skill. This can't be undone — export the skill first if you want a copy."
        confirmLabel={removeFile.isPending ? "Deleting…" : "Delete file"}
        onConfirm={confirmDeleteFile}
        onCancel={() => !removeFile.isPending && setDeleteFile(null)}
      />

      <ConfirmDialog
        open={deleteSkill}
        destructive
        title={`Delete the skill ${name}?`}
        description="All of its files are removed and the assistant can no longer use it. This can't be undone — export it first if you might need it again. Its run history is kept."
        confirmLabel={removeSkill.isPending ? "Deleting…" : "Delete skill"}
        onConfirm={confirmDeleteSkill}
        onCancel={() => !removeSkill.isPending && setDeleteSkill(false)}
      />
    </div>
  );
}
