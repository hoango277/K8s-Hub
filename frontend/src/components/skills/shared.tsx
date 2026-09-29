"use client";

import { CircleAlert } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Validation — mirrors the backend (app/modules/skills/parser.py and
// app/services/tool_service.py) so mistakes show under the field instead of
// as a 422 after pressing the button.
// ---------------------------------------------------------------------------

const SKILL_NAME_RE = /^[a-z0-9]+(-[a-z0-9]+)*$/;
export const SKILL_NAME_MAX = 64;
export const SKILL_DESCRIPTION_MAX = 1024;
export const SKILL_INSTRUCTIONS_MAX = 100_000;
/** The backend stops reading an upload after this many bytes. */
export const SKILL_ZIP_MAX = 10_000_000;
export const SCRIPT_ARGS_MAX = 20;

export function validateSkillName(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "Enter a name.";
  if (name.length > SKILL_NAME_MAX) return `Use at most ${SKILL_NAME_MAX} characters.`;
  if (!SKILL_NAME_RE.test(name))
    return "Use lowercase letters and digits, separated by single hyphens (e.g. diagnose-crashloop).";
  if (name.includes("anthropic") || name.includes("claude"))
    return "The name can't contain the reserved words “anthropic” or “claude”.";
  return null;
}

export function validateSkillDescription(raw: string): string | null {
  const text = raw.trim();
  if (!text) return "Describe what the skill does and when to use it.";
  if (text.length > SKILL_DESCRIPTION_MAX) return `Use at most ${SKILL_DESCRIPTION_MAX} characters.`;
  return null;
}

const SKILL_DIRS = ["scripts/", "references/", "assets/"];

/** A new file path: relative, inside the skill folder, in a known place. */
export function validateSkillFilePath(raw: string, existing: string[]): string | null {
  const path = raw.trim();
  if (!path) return "Enter a file path.";
  if (path.length > 200) return "Use at most 200 characters.";
  if (path.includes("\\")) return "Use forward slashes (/) in paths.";
  if (path.startsWith("/")) return "Use a path relative to the skill folder, without a leading /.";
  const parts = path.split("/");
  if (parts.some((p) => p === "" || p === "." || p === ".."))
    return "The path can't contain empty parts, “.” or “..”.";
  if (parts.length > 1 && !SKILL_DIRS.some((d) => path.startsWith(d)))
    return "Put files at the top level or inside scripts/, references/ or assets/.";
  if (existing.includes(path)) return "A file with this path already exists — open it from the list instead.";
  return null;
}

const MCP_NAME_RE = /^[a-z][a-z0-9-]{1,31}$/;

export function validateServerName(raw: string): string | null {
  const name = raw.trim();
  if (!name) return "Enter a name.";
  if (name.length < 2 || name.length > 32) return "Use 2 to 32 characters.";
  if (!MCP_NAME_RE.test(name)) return "Start with a letter; then use lowercase letters, digits and hyphens.";
  return null;
}

export function validateServerUrl(raw: string): string | null {
  const url = raw.trim();
  if (!url) return "Enter the server URL.";
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") throw new Error();
    if (!parsed.host) throw new Error();
  } catch {
    return "Enter a full http:// or https:// URL, e.g. http://host:8000/mcp.";
  }
  if (url.length > 500) return "Use at most 500 characters.";
  return null;
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
  return `${Math.floor(ms / 60_000)} min ${Math.round((ms % 60_000) / 1000)} s`;
}

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

export function isMarkdown(path: string): boolean {
  return /\.(md|markdown)$/i.test(path);
}

/**
 * Split shell-style arguments: spaces separate, quotes group, backslash
 * escapes. Deliberately tiny — the backend receives a list and never runs a
 * shell, so this only saves typing a list by hand.
 */
export function splitArgs(input: string): { args: string[]; error: string | null } {
  const args: string[] = [];
  let current = "";
  let quote: '"' | "'" | null = null;
  let inToken = false;
  for (let i = 0; i < input.length; i++) {
    const c = input[i];
    if (quote) {
      if (c === quote) quote = null;
      else if (c === "\\" && quote === '"' && i + 1 < input.length) current += input[++i];
      else current += c;
    } else if (c === '"' || c === "'") {
      quote = c;
      inToken = true;
    } else if (c === "\\" && i + 1 < input.length) {
      current += input[++i];
      inToken = true;
    } else if (/\s/.test(c)) {
      if (inToken) args.push(current);
      current = "";
      inToken = false;
    } else {
      current += c;
      inToken = true;
    }
  }
  if (quote) return { args: [], error: `Close the ${quote === '"' ? "double" : "single"} quote.` };
  if (inToken) args.push(current);
  if (args.length > SCRIPT_ARGS_MAX) return { args, error: `Use at most ${SCRIPT_ARGS_MAX} arguments.` };
  return { args, error: null };
}

/** Quote an argument back for display, only when it needs it. */
export function quoteArg(arg: string): string {
  return arg === "" || /[\s"'\\]/.test(arg) ? `"${arg.replace(/(["\\])/g, "\\$1")}"` : arg;
}

// ---------------------------------------------------------------------------
// Shared states
// ---------------------------------------------------------------------------

export function LoadingRow({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]">
      <Spinner /> {label}
    </div>
  );
}

export function ErrorPanel({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div role="alert" className="rounded-lg border border-[var(--destructive)]/40 bg-[var(--destructive)]/5 p-4 text-sm">
      <p className="font-medium text-[var(--destructive)]">{title}</p>
      <p className="mt-1 text-[var(--muted-foreground)]">
        {errorMessage(error, "Check that the backend is running, then try again.")}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

/** Server error shown next to a form's submit button. */
export function FormError({ error, fallback }: { error: unknown; fallback: string }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-[var(--destructive)]/30 bg-[var(--destructive)]/10 px-3 py-2.5 text-sm text-[var(--destructive)]"
    >
      <CircleAlert aria-hidden className="mt-0.5 size-4 shrink-0" />
      <span className="min-w-0 break-words">{errorMessage(error, fallback)}</span>
    </div>
  );
}

/** Monospace output block that scrolls inside itself instead of widening the page. */
export function OutputBlock({ text, className }: { text: string; className?: string }) {
  return (
    <pre
      className={cn(
        "max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-[var(--muted)] p-3 font-mono text-xs leading-relaxed",
        className,
      )}
    >
      {text || <span className="text-[var(--muted-foreground)]">(no output)</span>}
    </pre>
  );
}

export const textareaClass =
  "w-full rounded-md border bg-[var(--background)] px-3 py-2 text-sm outline-none transition " +
  "placeholder:text-[var(--muted-foreground)] focus-visible:border-[var(--ring)] focus-visible:ring-2 " +
  "focus-visible:ring-[var(--ring)]/40 disabled:cursor-not-allowed disabled:opacity-50 " +
  "aria-[invalid=true]:border-[var(--destructive)]";

/** Section title + description, with the section's own actions on the right. */
export function SectionHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4 border-b pb-4">
      <div className="min-w-0 max-w-2xl">
        <h2 id="section-title" className="text-lg font-semibold">
          {title}
        </h2>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">{description}</p>
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}
