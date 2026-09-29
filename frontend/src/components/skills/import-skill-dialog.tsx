"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { FileArchive } from "lucide-react";

import { FormError, SKILL_ZIP_MAX, formatBytes } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { inputClass } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useImportSkill } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";

const TITLE_ID = "import-skill-title";

export function ImportSkillDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const upload = useImportSkill();

  function close() {
    if (upload.isPending) return;
    upload.reset();
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} labelledBy={TITLE_ID}>
      <ImportForm upload={upload} onClose={close} />
    </Dialog>
  );
}

function validateFile(file: File | null): string | null {
  if (!file) return "Choose a .zip file.";
  if (!file.name.toLowerCase().endsWith(".zip")) return "Choose a .zip file — other archive types aren't supported.";
  if (file.size > SKILL_ZIP_MAX) return `The file is ${formatBytes(file.size)}; the limit is ${formatBytes(SKILL_ZIP_MAX)}.`;
  return null;
}

function ImportForm({ upload, onClose }: { upload: ReturnType<typeof useImportSkill>; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [touched, setTouched] = useState(false);

  const fileError = validateFile(file);
  const showError = touched ? fileError : null;
  const busy = upload.isPending;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (fileError || !file) return;
    upload.mutate(
      { file, replace },
      {
        onSuccess: (skill) => {
          toast({ kind: "ok", message: `Imported ${skill.name} with ${skill.files.length} files.` });
          onClose();
          router.push(`/skills/${encodeURIComponent(skill.name)}`);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogHeader
        id={TITLE_ID}
        icon={FileArchive}
        title="Import a skill"
        subtitle="Upload a skill folder packed as a .zip."
        onClose={onClose}
        closeDisabled={busy}
      />

      <div className="space-y-4 px-5 py-5">
        <p className="text-sm leading-relaxed text-[var(--muted-foreground)]">
          The archive must hold one skill folder with a <code>SKILL.md</code> at its top, plus any{" "}
          <code>scripts/</code>, <code>references/</code> and <code>assets/</code>. Exporting a skill gives you exactly
          this shape.
        </p>

        <div className="space-y-1.5">
          <label htmlFor="skill-zip" className="text-sm font-medium">
            Skill archive
          </label>
          <input
            id="skill-zip"
            type="file"
            accept=".zip,application/zip"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              setTouched(true);
              upload.reset();
            }}
            disabled={busy}
            aria-invalid={Boolean(showError)}
            aria-describedby="skill-zip-description"
            className={cn(
              inputClass,
              "h-auto py-1.5 file:mr-3 file:rounded-md file:border-0 file:bg-[var(--accent)] file:px-3 file:py-1 file:text-sm file:font-medium file:text-[var(--accent-foreground)]",
            )}
          />
          <p
            id="skill-zip-description"
            className={showError ? "text-xs text-[var(--destructive)]" : "text-xs text-[var(--muted-foreground)]"}
          >
            {showError ?? (file ? `${file.name} · ${formatBytes(file.size)}` : `Up to ${formatBytes(SKILL_ZIP_MAX)}.`)}
          </p>
        </div>

        <label className="flex cursor-pointer items-start gap-3 rounded-md border p-3 has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-[var(--ring)]">
          <input
            type="checkbox"
            checked={replace}
            onChange={(e) => setReplace(e.target.checked)}
            disabled={busy}
            className="mt-0.5 size-4 accent-[var(--primary)]"
          />
          <span className="text-sm">
            <span className="font-medium">Replace a custom skill with the same name</span>
            <span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">
              Its files are overwritten with the archive&apos;s. Built-in skills are never replaced.
            </span>
          </span>
        </label>

        <FormError error={upload.error} fallback="Couldn't import the archive. Try again." />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Spinner className="text-current" label="Importing" />}
          {busy ? "Importing…" : "Import"}
        </Button>
      </DialogFooter>
    </form>
  );
}
