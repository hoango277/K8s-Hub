/**
 * How each backend setting is presented: human label, section, unit, control.
 *
 * The backend describes fields generically (type, bounds, .env name); this
 * file turns them into a settings page a person can read without knowing the
 * .env names. A field the backend adds but this file doesn't know yet still
 * shows up — under "Other", with a generic control — so nothing silently
 * disappears.
 */

import { Bot, Cable, History, KeyRound, Server, SlidersHorizontal, type LucideIcon } from "lucide-react";

export type SectionId = "model" | "keys" | "cluster" | "other" | "connections" | "history" | "advanced";

export interface SectionMeta {
  id: SectionId;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Sections that hold editable fields take part in the unsaved-changes bar. */
  editable: boolean;
}

export const SECTIONS: SectionMeta[] = [
  {
    id: "model",
    label: "AI model",
    description: "How the assistant calls the language model. Applies to every conversation.",
    icon: Bot,
    editable: true,
  },
  {
    id: "keys",
    label: "API keys",
    description: "Keys for the model providers. Stored encrypted and never shown again after saving.",
    icon: KeyRound,
    editable: true,
  },
  {
    id: "cluster",
    label: "Cluster access",
    description: "What the assistant is allowed to do on the Kubernetes cluster.",
    icon: Server,
    editable: true,
  },
  {
    id: "other",
    label: "Other",
    description: "Settings without a dedicated section yet.",
    icon: SlidersHorizontal,
    editable: true,
  },
  {
    id: "connections",
    label: "Connections",
    description: "Whether the services this app depends on are reachable right now.",
    icon: Cable,
    editable: false,
  },
  {
    id: "history",
    label: "Change history",
    description: "Every change made on this page: who, what, and when.",
    icon: History,
    editable: false,
  },
  {
    id: "advanced",
    label: "Advanced",
    description: "Reload defaults from the server, or undo every change made here.",
    icon: SlidersHorizontal,
    editable: false,
  },
];

export type Control = "slider" | "number" | "modes" | "namespaces" | "apikey" | "generic";

export interface FieldMeta {
  label: string;
  section: SectionId;
  control: Control;
  /** Replaces the backend description when a clearer sentence helps. */
  help?: string;
  /** Shown inside number inputs, e.g. "tokens". */
  unit?: string;
  /** Slider end labels. */
  scale?: [string, string];
  step?: number;
  /** For API keys. */
  provider?: { id: string; name: string; keysUrl: string };
}

export const FIELDS: Record<string, FieldMeta> = {
  LLM_TEMPERATURE: {
    label: "Temperature",
    section: "model",
    control: "slider",
    step: 0.1,
    scale: ["Precise", "Creative"],
    help: "Keep it at 0 so action plans come out the same every time. Raise it only for open-ended answers.",
  },
  LLM_MAX_TOKENS: {
    label: "Max response length",
    section: "model",
    control: "number",
    unit: "tokens",
    help: "Longer limits allow fuller answers but cost more and take longer.",
  },
  LLM_TIMEOUT_SECONDS: {
    label: "Response timeout",
    section: "model",
    control: "number",
    unit: "seconds",
    step: 1,
    help: "How long to wait for the model before giving up on a turn.",
  },
  LLM_MAX_RETRIES: {
    label: "Retries",
    section: "model",
    control: "number",
    unit: "times",
    help: "Extra attempts when the provider rate-limits or the network fails.",
  },
  GROQ_API_KEY: {
    label: "Groq",
    section: "keys",
    control: "apikey",
    provider: { id: "groq", name: "Groq", keysUrl: "https://console.groq.com/keys" },
  },
  GOOGLE_API_KEY: {
    label: "Google Gemini",
    section: "keys",
    control: "apikey",
    provider: { id: "google", name: "Google Gemini", keysUrl: "https://aistudio.google.com/apikey" },
  },
  K8S_EXECUTION_MODE: {
    label: "Execution mode",
    section: "cluster",
    control: "modes",
    help: "Decides whether a change planned by the assistant needs a person to approve it.",
  },
  K8S_ALLOWED_NAMESPACES: {
    label: "Allowed namespaces",
    section: "cluster",
    control: "namespaces",
    help: "The assistant only reads and acts inside these namespaces. Leave empty to allow all.",
  },
};

/** Position of a field inside its section: the order of FIELDS above. */
const ORDER = Object.keys(FIELDS);
export function fieldOrder(name: string): number {
  const i = ORDER.indexOf(name);
  return i === -1 ? ORDER.length : i;
}

export function fieldMeta(name: string, type: string): FieldMeta {
  return FIELDS[name] ?? { label: name, section: "other", control: type === "secret" ? "apikey" : "generic" };
}

export interface ModeOption {
  value: string;
  label: string;
  description: string;
  recommended?: boolean;
  dangerous?: boolean;
}

export const EXECUTION_MODES: ModeOption[] = [
  {
    value: "read_only",
    label: "Read only",
    description: "The assistant can look at the cluster but never changes anything.",
  },
  {
    value: "require_approval",
    label: "Require approval",
    description: "Every change the assistant plans waits for a person to approve it.",
    recommended: true,
  },
  {
    value: "auto",
    label: "Automatic",
    description: "Changes run without approval. Only for test clusters you can afford to break.",
    dangerous: true,
  },
];

/** Readable form of a setting value, for history and "default" hints. */
export function formatValue(name: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (name === "K8S_EXECUTION_MODE") {
    return EXECUTION_MODES.find((m) => m.value === value)?.label ?? String(value);
  }
  if (Array.isArray(value)) return value.length ? value.join(", ") : "all";
  const unit = FIELDS[name]?.unit;
  return unit ? `${String(value)} ${unit}` : String(value);
}
