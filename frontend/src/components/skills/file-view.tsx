"use client";

import { useEffect, useState } from "react";
import { Eye, FileQuestion, Pencil, Save, Trash2, Undo2 } from "lucide-react";

import { Markdown } from "@/components/chat/markdown";
import {
  ErrorPanel,
  FormError,
  LoadingRow,
  formatBytes,
  isMarkdown,
  textareaClass,
} from "@/components/skills/shared";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useSkillFile, useWriteSkillFile } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";

/** Split SKILL.md's YAML front matter from the body, so the preview shows the
 * metadata as a table instead of a stray rule and a run-on paragraph. */
function splitFrontmatter(text: string): { header: string | null; body: string } {
  if (!text.startsWith("---")) return { header: null, body: text };
  const end = text.indexOf("\n---", 3);
  if (end === -1) return { header: null, body: text };
  const afterClose = text.indexOf("\n", end + 4);
  return { header: text.slice(3, end).trim(), body: afterClose === -1 ? "" : text.slice(afterClose + 1) };
}

function formatFrontmatterValue(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

interface Props {
  skill: string;
  path: string;
  size: number;
  /** Custom skill + engineer role: the file can be changed. */
  editable: boolean;
  /** SKILL.md's parsed front matter from the server — nicer than re-parsing YAML here. */
  frontmatter: Record<string, unknown> | null;
  onDirtyChange: (dirty: boolean) => void;
  onDelete: (() => void) | null;
}

/**
 * One file of a skill. Keyed by path in the parent, so switching files starts
 * from a clean slate (no draft of the previous file leaking in).
 */
export function FileView({ skill, path, size, editable, frontmatter, onDirtyChange, onDelete }: Props) {
  const { data: file, isLoading, error, refetch } = useSkillFile(skill, path);
  const write = useWriteSkillFile();
  const toast = useToast();

  const markdown = isMarkdown(path);
  // Markdown opens as a preview; other text files open straight in the editor
  // (or a read-only viewer) since there's nothing to render.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const original = file?.text ?? "";
  const dirty = draft !== null && draft !== original;

  useEffect(() => {
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);

  // Report "clean" when this file view goes away (switching files, leaving).
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);

  function save() {
    if (draft === null || !dirty) return;
    write.mutate(
      { name: skill, path, text: draft },
      {
        onSuccess: () => {
          setDraft(null);
          if (markdown) setEditing(false);
          toast({ kind: "ok", message: `Saved ${path}.` });
        },
      },
    );
  }

  function discard() {
    setDraft(null);
    write.reset();
    if (markdown) setEditing(false);
    setConfirmDiscard(false);
  }

  const showEditor = editable && (!markdown || editing);

  return (
    <div className="min-w-0 rounded-lg border">
      <header className="flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <h2 className="min-w-0 flex-1 break-all font-mono text-sm font-medium">{path}</h2>
        <span className="text-xs text-[var(--muted-foreground)]">{formatBytes(file?.size ?? size)}</span>
        {dirty && <Badge tone="warning">Unsaved</Badge>}
        {markdown && editable && file?.text !== null && (
          <div role="group" aria-label="View mode" className="flex rounded-md border p-0.5">
            {(
              [
                [false, "Preview", Eye],
                [true, "Edit", Pencil],
              ] as const
            ).map(([mode, label, Icon]) => (
              <button
                key={label}
                type="button"
                aria-pressed={editing === mode}
                onClick={() => setEditing(mode)}
                className={cn(
                  "flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
                  editing === mode
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
                )}
              >
                <Icon aria-hidden className="size-3.5" />
                {label}
              </button>
            ))}
          </div>
        )}
        {onDelete && (
          <Button variant="ghost" size="icon" onClick={onDelete} aria-label={`Delete ${path}`}>
            <Trash2 aria-hidden />
          </Button>
        )}
      </header>

      <div className="p-4">
        {isLoading ? (
          <LoadingRow label="Loading file…" />
        ) : error || !file ? (
          <ErrorPanel title={`Couldn't open ${path}`} error={error} onRetry={() => void refetch()} />
        ) : file.text === null ? (
          <div className="flex flex-col items-center gap-2 py-10 text-center">
            <FileQuestion aria-hidden className="size-8 text-[var(--muted-foreground)]" />
            <p className="text-sm font-medium">Binary file · {formatBytes(file.size)}</p>
            <p className="max-w-sm text-xs text-[var(--muted-foreground)]">
              It can&apos;t be shown here. Export the skill as a .zip to get a copy.
            </p>
          </div>
        ) : showEditor ? (
          <div className="space-y-3">
            <label htmlFor={`editor-${path}`} className="sr-only">
              Content of {path}
            </label>
            <textarea
              id={`editor-${path}`}
              spellCheck={false}
              rows={Math.min(30, Math.max(12, (draft ?? original).split("\n").length + 2))}
              className={cn(textareaClass, "font-mono text-xs leading-relaxed")}
              value={draft ?? original}
              onChange={(e) => {
                setDraft(e.target.value);
                write.reset();
              }}
              onKeyDown={(e) => {
                // Ctrl/Cmd+S saves, as in any editor, instead of the browser's "save page".
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
                  e.preventDefault();
                  save();
                }
              }}
              disabled={write.isPending}
            />
            {path === "SKILL.md" && (
              <p className="text-xs text-[var(--muted-foreground)]">
                Keep the front matter between the <code>---</code> lines. <code>name</code> must stay{" "}
                <code>{skill}</code>; <code>description</code> is what the assistant reads to decide when to use it.
              </p>
            )}
            <FormError error={write.error} fallback="Couldn't save the file. Try again." />
            <div className="flex flex-wrap justify-end gap-2">
              {(markdown || dirty) && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => (dirty ? setConfirmDiscard(true) : discard())}
                  disabled={write.isPending}
                >
                  <Undo2 aria-hidden />
                  {markdown ? "Cancel" : "Revert"}
                </Button>
              )}
              <Button size="sm" onClick={save} disabled={write.isPending || !dirty}>
                {write.isPending ? <Spinner className="text-current" label="Saving" /> : <Save aria-hidden />}
                {write.isPending ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
        ) : markdown ? (
          <MarkdownPreview text={draft ?? file.text} frontmatter={path === "SKILL.md" ? frontmatter : null} />
        ) : (
          <pre className="max-h-[36rem] overflow-auto whitespace-pre rounded-md bg-[var(--muted)] p-3 font-mono text-xs leading-relaxed">
            {file.text || <span className="text-[var(--muted-foreground)]">(empty file)</span>}
          </pre>
        )}
      </div>

      <ConfirmDialog
        open={confirmDiscard}
        destructive
        title="Discard your changes?"
        description={`Your edits to ${path} haven't been saved and will be lost.`}
        confirmLabel="Discard changes"
        cancelLabel="Keep editing"
        onConfirm={discard}
        onCancel={() => setConfirmDiscard(false)}
      />
    </div>
  );
}

function MarkdownPreview({ text, frontmatter }: { text: string; frontmatter: Record<string, unknown> | null }) {
  const { header, body } = splitFrontmatter(text);
  const entries = frontmatter ? Object.entries(frontmatter) : [];
  return (
    <div className="space-y-4">
      {header !== null && entries.length > 0 && (
        <dl className="grid gap-x-4 gap-y-2 rounded-md border bg-[var(--muted)]/40 p-3 text-xs sm:grid-cols-[8rem_minmax(0,1fr)]">
          {entries.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="font-mono text-[var(--muted-foreground)]">{key}</dt>
              <dd className="break-words">{formatFrontmatterValue(value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {body.trim() ? (
        <Markdown className="min-w-0 break-words">{body}</Markdown>
      ) : (
        <p className="text-sm text-[var(--muted-foreground)]">
          {/* Only SKILL.md carries front matter; other Markdown files are just empty. */}
          {frontmatter ? "No instructions yet." : "This file is empty."}
        </p>
      )}
    </div>
  );
}
