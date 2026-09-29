"use client";

import { useState } from "react";
import { Plug } from "lucide-react";

import { FormError, validateServerName, validateServerUrl } from "@/components/skills/shared";
import { Button } from "@/components/ui/button";
import { Dialog, DialogFooter, DialogHeader } from "@/components/ui/dialog";
import { Field, Input, PasswordInput } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useAddMcpServer } from "@/hooks/use-tools";

const TITLE_ID = "add-server-title";

export function AddServerDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const add = useAddMcpServer();

  function close() {
    if (add.isPending) return;
    add.reset();
    onClose();
  }

  return (
    <Dialog open={open} onClose={close} labelledBy={TITLE_ID}>
      <AddForm add={add} onClose={close} />
    </Dialog>
  );
}

function AddForm({ add, onClose }: { add: ReturnType<typeof useAddMcpServer>; onClose: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [touched, setTouched] = useState({ name: false, url: false });

  const nameError = validateServerName(name);
  const urlError = validateServerUrl(url);
  const tokenError = token.length > 4000 ? "Use at most 4000 characters." : null;
  const busy = add.isPending;

  const showName = touched.name ? nameError : null;
  const showUrl = touched.url ? urlError : null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setTouched({ name: true, url: true });
    if (nameError || urlError || tokenError) return;
    add.mutate(
      { name: name.trim(), url: url.trim(), ...(token ? { token } : {}) },
      {
        onSuccess: (s) => {
          toast(
            s.last_error
              ? { kind: "error", message: `Added ${s.name}, but it didn't answer: ${s.last_error}` }
              : {
                  kind: "ok",
                  message: `Connected ${s.name}. Its ${s.tool_count} ${s.tool_count === 1 ? "tool is" : "tools are"} under Tools, disabled until reviewed.`,
                },
          );
          onClose();
        },
      },
    );
  }

  return (
    <form onSubmit={submit} noValidate>
      <DialogHeader
        id={TITLE_ID}
        icon={Plug}
        title="Add MCP server"
        subtitle="Its tools are read right away and start disabled."
        onClose={onClose}
        closeDisabled={busy}
      />

      <div className="space-y-4 px-5 py-5">
        <Field
          id="server-name"
          label="Name"
          error={showName}
          hint="A short id shown next to its tools, e.g. jira. Lowercase letters, digits and hyphens."
        >
          <Input
            id="server-name"
            autoFocus
            autoComplete="off"
            spellCheck={false}
            className="font-mono"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, name: true }))}
            disabled={busy}
            aria-invalid={Boolean(showName)}
            aria-describedby="server-name-description"
          />
        </Field>

        <Field id="server-url" label="URL" error={showUrl} hint="The server's streamable HTTP endpoint.">
          <Input
            id="server-url"
            type="url"
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            placeholder="http://host:8000/mcp"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            onBlur={() => setTouched((t) => ({ ...t, url: true }))}
            disabled={busy}
            aria-invalid={Boolean(showUrl)}
            aria-describedby="server-url-description"
          />
        </Field>

        <Field
          id="server-token"
          label="Access token (optional)"
          error={tokenError}
          hint="Sent as a Bearer token. Stored encrypted and never shown again."
        >
          <PasswordInput
            id="server-token"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            disabled={busy}
            aria-invalid={Boolean(tokenError)}
            aria-describedby="server-token-description"
          />
        </Field>

        <FormError error={add.error} fallback="Couldn't add the server. Try again." />
      </div>

      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button type="submit" disabled={busy}>
          {busy && <Spinner className="text-current" label="Connecting" />}
          {busy ? "Connecting…" : "Add server"}
        </Button>
      </DialogFooter>
    </form>
  );
}
