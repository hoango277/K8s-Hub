/**
 * Settings that can be changed at runtime.
 *
 * Must match `backend/app/api/v1/settings.py`.
 */

export type FieldType =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "enum"
  | "list"
  | "object"
  | "secret";

export interface SettingField {
  name: string;
  type: FieldType;
  /** Allowed values, only present when type === "enum" */
  options: string[] | null;
  minimum: number | null;
  maximum: number | null;
  exclusive_minimum: number | null;
  exclusive_maximum: number | null;
  secret: boolean;
  description: string;
  /** Current value. Always null for secrets. */
  value: unknown;
  /** Whether the secret has been set. Only meaningful when secret === true. */
  is_set: boolean | null;
  /** Original value from .env, used by the restore button. */
  env_value: unknown;
  /** Whether it currently differs from .env. */
  overridden: boolean;
}

export interface SettingsView {
  /** Incremented after every change. Used to detect that someone else just edited. */
  version: number;
  fields: SettingField[];
  /** The active overrides; secret values are masked as "***". */
  overrides: Record<string, unknown>;
}

export interface SettingsPatch {
  /** Set to null to drop a field's override, returning it to the .env value. */
  values: Record<string, unknown>;
  replace?: boolean;
}

/** Display group in the UI, derived from the field name prefix. */
export type SettingGroup = "LLM" | "Kubernetes" | "Observability" | "General";

export function groupOf(name: string): SettingGroup {
  if (name.startsWith("LLM_") || name.endsWith("_API_KEY")) return "LLM";
  if (name.startsWith("K8S_")) return "Kubernetes";
  if (name.startsWith("LANGFUSE_") || name.startsWith("PROMETHEUS_") || name.startsWith("LOKI_"))
    return "Observability";
  return "General";
}

export const GROUP_ORDER: SettingGroup[] = ["LLM", "Kubernetes", "Observability", "General"];

/** Options that need a warning because they are high-risk. */
export const DANGEROUS_OPTIONS: Record<string, string[]> = {
  K8S_EXECUTION_MODE: ["auto"],
};
