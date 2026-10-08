"use client";

import { useId, useState } from "react";
import { useRouter } from "next/navigation";
import { Stethoscope } from "lucide-react";

import { FormError } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader, useDialogContainer } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/components/ui/toast";
import { useRcaTargets, useRcaWorkloads, useStartRca } from "@/hooks/use-rca";

const WHOLE_NAMESPACE = "__all__";
// Select value for "diagnose everything" (the API takes no namespace).
const WHOLE_CLUSTER = "__cluster__";
const WINDOWS = [
  { minutes: 30, label: "Last 30 minutes" },
  { minutes: 60, label: "Last hour" },
  { minutes: 120, label: "Last 2 hours" },
  { minutes: 360, label: "Last 6 hours" },
  { minutes: 1440, label: "Last 24 hours" },
];
// Same rule as the backend (DNS-1123 label): checked here so the user sees it under the field.
const NAMESPACE = /^[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?$/;

export function NewDiagnosisDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const titleId = useId();
  return (
    <Dialog open={open} onClose={onClose} labelledBy={titleId} width="34rem">
      {open && <NewDiagnosisForm titleId={titleId} onClose={onClose} />}
    </Dialog>
  );
}

function NewDiagnosisForm({ titleId, onClose }: { titleId: string; onClose: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const container = useDialogContainer();
  const targets = useRcaTargets(true);
  const start = useStartRca();
  const ids = { ns: useId(), workload: useId(), window: useId(), report: useId() };

  const [namespace, setNamespace] = useState("");
  const [workload, setWorkload] = useState(WHOLE_NAMESPACE);
  const [minutes, setMinutes] = useState("120");
  const [withReport, setWithReport] = useState(true);
  const [submitted, setSubmitted] = useState(false);

  const listed = targets.data?.namespaces ?? [];
  // No list (no cluster access from the backend, or an error): type it instead.
  const typed = !targets.isLoading && listed.length === 0;
  // Typed mode: an empty field means the whole cluster too.
  const cluster = namespace === WHOLE_CLUSTER || (typed && namespace === "");
  const validNs = cluster || NAMESPACE.test(namespace);
  const workloads = useRcaWorkloads(validNs && !cluster && !typed ? namespace : null);
  const nsError =
    submitted && !validNs
      ? namespace
        ? "Use lowercase letters, digits and dashes."
        : "Choose a namespace or the whole cluster."
      : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitted(true);
    if (!validNs) return;
    const target = workloads.data?.find((w) => w.name === workload);
    start.mutate(
      {
        namespace: cluster ? null : namespace,
        target_kind: target ? "Workload" : null,
        target_name: target?.name ?? null,
        lookback_minutes: Number(minutes),
        with_report: withReport,
      },
      {
        onSuccess: (run) => {
          const what = cluster ? "the whole cluster" : target ? `${namespace}/${target.name}` : namespace;
          toast({ kind: "ok", message: `Diagnosing ${what}…` });
          onClose();
          router.push(`/rca/${run.id}`);
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogHeader
        id={titleId}
        icon={Stethoscope}
        title="New diagnosis"
        subtitle="Find the likely root cause of what is going wrong."
        onClose={onClose}
        closeDisabled={start.isPending}
      />
      <div className="space-y-4 px-5 py-4">
        {typed ? (
          <Field
            id={ids.ns}
            label="Namespace"
            hint={targets.data?.error ? "The namespace list isn't available; type the name." : undefined}
            error={nsError}
          >
            <Input
              id={ids.ns}
              value={namespace}
              onChange={(e) => setNamespace(e.target.value.trim())}
              placeholder="e.g. shop — empty for the whole cluster"
              autoComplete="off"
              aria-invalid={Boolean(nsError)}
              aria-describedby={`${ids.ns}-description`}
            />
          </Field>
        ) : (
          <Field id={ids.ns} label="Namespace" error={nsError}>
            <Select
              value={namespace || undefined}
              onValueChange={(v) => {
                setNamespace(v);
                setWorkload(WHOLE_NAMESPACE);
              }}
              disabled={targets.isLoading}
            >
              <SelectTrigger
                id={ids.ns}
                className="w-full justify-between"
                aria-invalid={Boolean(nsError)}
                aria-describedby={`${ids.ns}-description`}
              >
                <SelectValue placeholder={targets.isLoading ? "Loading namespaces…" : "Choose a namespace or the whole cluster"} />
              </SelectTrigger>
              <SelectContent container={container}>
                <SelectItem value={WHOLE_CLUSTER} description="Every namespace, for problems you can't place yet">
                  Whole cluster
                </SelectItem>
                {listed.map((n) => (
                  <SelectItem key={n} value={n}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}

        <Field
          id={ids.workload}
          label="Focus on"
          hint="Optional. Its symptoms are explained first; causes are searched in the namespace and in the services it depends on, in any namespace."
        >
          <Select value={workload} onValueChange={setWorkload} disabled={!validNs || typed || cluster}>
            <SelectTrigger id={ids.workload} className="w-full justify-between" aria-describedby={`${ids.workload}-description`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent container={container}>
              <SelectItem value={WHOLE_NAMESPACE}>The whole namespace</SelectItem>
              {(workloads.data ?? []).map((w) => (
                <SelectItem key={`${w.kind}/${w.name}`} value={w.name} description={w.kind}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <Field id={ids.window} label="Look back" hint="Causes often come minutes to hours before the symptom.">
          <Select value={minutes} onValueChange={setMinutes}>
            <SelectTrigger id={ids.window} className="w-full justify-between" aria-describedby={`${ids.window}-description`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent container={container}>
              {WINDOWS.map((w) => (
                <SelectItem key={w.minutes} value={String(w.minutes)}>
                  {w.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>

        <div className="flex items-start justify-between gap-4 rounded-lg border p-3">
          <div className="min-w-0">
            <label htmlFor={ids.report} className="text-sm font-medium">
              AI report
            </label>
            <p id={`${ids.report}-hint`} className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              The AI checks the top causes with a few read-only lookups and writes a summary. Takes up to a minute.
            </p>
          </div>
          <Switch
            id={ids.report}
            checked={withReport}
            onCheckedChange={setWithReport}
            aria-describedby={`${ids.report}-hint`}
          />
        </div>

        <FormError error={start.error} fallback="The diagnosis could not be started." />
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={start.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={start.isPending}>
          {start.isPending && <Spinner />}
          Start diagnosis
        </Button>
      </DialogFooter>
    </form>
  );
}
