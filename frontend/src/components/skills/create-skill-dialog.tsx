"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { BookPlus } from "lucide-react";

import {
  FormError,
  SKILL_DESCRIPTION_MAX,
  SKILL_INSTRUCTIONS_MAX,
  textareaClass,
  validateSkillDescription,
  validateSkillName,
} from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useCreateSkill } from "@/hooks/use-skills";

const TITLE_ID = "create-skill-title";

export function CreateSkillDialog({
  open,
  onClose,
  existing,
}: {
  open: boolean;
  onClose: () => void;
  existing: string[];
}) {
  const create = useCreateSkill();

  function close() {
    if (create.isPending) return;
    create.reset();
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} labelledBy={TITLE_ID} width="36rem">
      <CreateForm create={create} existing={existing} onClose={close} />
    </Dialog>
  );
}

function CreateForm({
  create,
  existing,
  onClose,
}: {
  create: ReturnType<typeof useCreateSkill>;
  existing: string[];
  onClose: () => void;
}) {
  const router = useRouter();
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");
  // Errors appear once a field is left or the form is submitted — not while
  // the first letter is still being typed.
  const [touched, setTouched] = useState({ name: false, description: false });

  const nameError =
    validateSkillName(name) ?? (existing.includes(name.trim()) ? "A skill with this name already exists." : null);
  const descriptionError = validateSkillDescription(description);
  const instructionsError =
    instructions.length > SKILL_INSTRUCTIONS_MAX ? `Use at most ${SKILL_INSTRUCTIONS_MAX.toLocaleString()} characters.` : null;
  const invalid = Boolean(nameError || descriptionError || instructionsError);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ name: true, description: true });
    if (invalid) return;
    const payload = { name: name.trim(), description: description.trim(), instructions };
    create.mutate(payload, {
      onSuccess: (skill) => {
        toast({ kind: "ok", message: `Created ${skill.name}. Add scripts or references from its page.` });
        onClose();
        router.push(`/skills/${encodeURIComponent(skill.name)}`);
      },
    });
  }

  const busy = create.isPending;
  const showName = touched.name ? nameError : null;
  const showDescription = touched.description ? descriptionError : null;

  return (
    <form onSubmit={submit} noValidate className="flex max-h-[calc(100dvh-2rem)] flex-col">
      <DialogHeader
        id={TITLE_ID}
        icon={BookPlus}
        title="New skill"
        subtitle="Creates a SKILL.md you can extend with files afterwards."
        onClose={onClose}
        closeDisabled={busy}
      />

      <div className="min-h-0 space-y-4 overflow-y-auto px-5 py-5">
        <Field
          id="skill-name"
          label="Name"
          error={showName}
          hint="Lowercase letters, digits and single hyphens, up to 64 characters. It can't be changed later."
        >
          <Input
            id="skill-name"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            placeholder="diagnose-crashloop"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
            disabled={busy}
            aria-invalid={Boolean(showName)}
            aria-describedby="skill-name-description"
          />
        </Field>

        <div className="space-y-1.5">
          <div className="flex items-baseline justify-between gap-2">
            <label htmlFor="skill-description" className="text-sm font-medium">
              Description
            </label>
            <span className="text-xs tabular-nums text-[var(--muted-foreground)]">
              {description.trim().length}/{SKILL_DESCRIPTION_MAX}
            </span>
          </div>
          <textarea
            id="skill-description"
            rows={3}
            className={textareaClass}
            placeholder="Diagnose pods stuck in CrashLoopBackOff. Use when a pod keeps restarting."
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, description: true }))}
            disabled={busy}
            aria-invalid={Boolean(showDescription)}
            aria-describedby="skill-description-description"
          />
          <p
            id="skill-description-description"
            className={showDescription ? "text-xs text-[var(--destructive)]" : "text-xs text-[var(--muted-foreground)]"}
          >
            {showDescription ??
              "The assistant only sees this until it opens the skill — say what it does AND when to use it."}
          </p>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="skill-instructions" className="text-sm font-medium">
            Instructions <span className="font-normal text-[var(--muted-foreground)]">(optional)</span>
          </label>
          <textarea
            id="skill-instructions"
            rows={9}
            spellCheck={false}
            className={`${textareaClass} font-mono text-xs leading-relaxed`}
            placeholder={"## Steps\n1. List the pods in the namespace with list_pods.\n2. …"}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            disabled={busy}
            aria-invalid={Boolean(instructionsError)}
            aria-describedby="skill-instructions-description"
          />
          <p
            id="skill-instructions-description"
            className={instructionsError ? "text-xs text-[var(--destructive)]" : "text-xs text-[var(--muted-foreground)]"}
          >
            {instructionsError ?? "Markdown. Name the tools to use and the steps to follow; you can edit it later."}
          </p>
        </div>

        <FormError error={create.error} fallback="Couldn't create the skill. Try again." />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Spinner className="text-current" label="Creating" />}
          {busy ? "Creating…" : "Create skill"}
        </Button>
      </DialogFooter>
    </form>
  );
}
