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

/** One row of the append-only change history. */
export interface SettingChange {
  id: string;
  changed_at: string;
  actor_email: string;
  action: "update" | "restore" | "reset_all" | "reload_env";
  field: string | null;
  /** Always null for secrets — keys are never logged. */
  old_value: unknown;
  new_value: unknown;
  secret: boolean;
}

export interface SettingChangePage {
  items: SettingChange[];
  total: number;
}

/** Reachability of one service the backend talks to. */
export interface ConnectionStatus {
  id: string;
  name: string;
  purpose: string;
  /** Address checked — never includes credentials. */
  target: string;
  /** null = not enabled, so not checked. */
  ok: boolean | null;
  version: string | null;
  detail: string | null;
  latency_ms: number | null;
}
