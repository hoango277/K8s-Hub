"use client";

import { useState } from "react";
import { FilePlus } from "lucide-react";

import { FormError, textareaClass, validateSkillFilePath } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useWriteSkillFile } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";

const TITLE_ID = "add-file-title";

export function AddFileDialog({
  open,
  skill,
  existing,
  onClose,
  onCreated,
}: {
  open: boolean;
  skill: string;
  existing: string[];
  onClose: () => void;
  onCreated: (path: string) => void;
}) {
  const write = useWriteSkillFile();

  function close() {
    if (write.isPending) return;
    write.reset();
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} labelledBy={TITLE_ID} width="36rem">
      <AddFileForm write={write} skill={skill} existing={existing} onClose={close} onCreated={onCreated} />
    </Dialog>
  );
}

function AddFileForm({
  write,
  skill,
  existing,
  onClose,
  onCreated,
}: {
  write: ReturnType<typeof useWriteSkillFile>;
  skill: string;
  existing: string[];
  onClose: () => void;
  onCreated: (path: string) => void;
}) {
  const toast = useToast();
  const [path, setPath] = useState("");
  const [text, setText] = useState("");
  const [touched, setTouched] = useState(false);

  const pathError = validateSkillFilePath(path, existing);
  const showError = touched ? pathError : null;
  const busy = write.isPending;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (pathError) return;
    const clean = path.trim();
    write.mutate(
      { name: skill, path: clean, text },
      {
        onSuccess: () => {
          toast({ kind: "ok", message: `Added ${clean}.` });
          onCreated(clean);
          onClose();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate className="flex max-h-[calc(100dvh-2rem)] flex-col">
      <DialogHeader
        id={TITLE_ID}
        icon={FilePlus}
        title="Add file"
        subtitle={<code>{skill}</code>}
        onClose={onClose}
        closeDisabled={busy}
      />

      <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5">
        <Field
          id="file-path"
          label="Path"
          error={showError}
          hint="scripts/ for code the assistant can run (.py or .sh), references/ for documents it reads, assets/ for templates."
        >
          <Input
            id="file-path"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            placeholder="references/checklist.md"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            onBlur={() => setTouched(true)}
            disabled={busy}
            aria-invalid={Boolean(showError)}
            aria-describedby="file-path-description"
          />
        </Field>

        <div className="space-y-1.5">
          <label htmlFor="file-content" className="text-sm font-medium">
            Content <span className="font-normal text-[var(--muted-foreground)]">(optional)</span>
          </label>
          <textarea
            id="file-content"
            rows={10}
            spellCheck={false}
            className={cn(textareaClass, "font-mono text-xs leading-relaxed")}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
          />
          <p className="text-xs text-[var(--muted-foreground)]">Text files only — you can edit it after creating.</p>
        </div>

        <FormError error={write.error} fallback="Couldn't add the file. Try again." />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Spinner className="text-current" label="Adding" />}
          {busy ? "Adding…" : "Add file"}
        </Button>
      </DialogFooter>
    </form>
  );
}
