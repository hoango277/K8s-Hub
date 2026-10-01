/**
 * Tool catalog and custom CLI tools — matches backend/app/api/v1/tools.py.
 * Change one side, change the other.
 */

export type ToolCategory = "kubernetes" | "metrics" | "logs" | "traces" | "custom" | "mcp";
export type ToolDanger = "read" | "write" | "destructive";

/** The subset of JSON Schema that Pydantic emits for tool arguments. */
export interface JsonSchemaProperty {
  type?: string;
  anyOf?: JsonSchemaProperty[];
  enum?: unknown[];
  items?: JsonSchemaProperty;
  default?: unknown;
  description?: string;
  title?: string;
  minimum?: number;
  maximum?: number;
}

export interface JsonSchemaObject {
  type?: string;
  properties?: Record<string, JsonSchemaProperty>;
  required?: string[];
}

export interface Tool {
  name: string;
  title: string;
  description: string;
  category: ToolCategory;
  /** "builtin", "custom" (a CLI tool defined on this page) or "mcp:<server>". */
  source: string;
  danger: ToolDanger;
  enabled: boolean;
  available: boolean;
  /** Why it can't run right now (disabled, not read-only, backend missing…). */
  unavailable_reason: string | null;
  /** Whether the assistant can call it right now. */
  in_chat: boolean;
  input_schema: JsonSchemaObject;
  /** Custom tools only: their definition, for editing. */
  custom: CustomTool | null;
  /** MCP tools only: their server and the policy an engineer set. */
  mcp: McpToolInfo | null;
}

export interface McpToolInfo {
  server: string;
  /** What the server CLAIMS — shown as a hint, never trusted. */
  read_only_hint: boolean | null;
  /** Each call waits for an engineer's approval (default for new tools). */
  requires_approval: boolean;
}

export interface ToolPatch {
  enabled?: boolean;
  /** MCP tools only. */
  requires_approval?: boolean;
}

export interface McpServer {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  has_token: boolean;
  tool_count: number;
  last_error: string | null;
  refreshed_at: string | null;
}

export interface McpServerCreate {
  name: string;
  url: string;
  token?: string;
}

/** A CLI wrapped as a tool (kubectl-ai style). The assistant writes only the
 * arguments; calls starting with a read-only subcommand run at once, anything
 * else waits for approval. */
export interface CustomToolFields {
  title: string;
  /** When the assistant should use it. */
  description: string;
  /** The program, e.g. "kubectl". */
  command: string;
  /** Syntax and examples for the assistant. */
  usage: string;
  /** e.g. ["get", "describe", "rollout status"] */
  read_only_prefixes: string[];
  timeout_seconds: number;
  enabled: boolean;
}

export interface CustomTool extends CustomToolFields {
  name: string;
}

export interface ToolRun {
  id: string;
  tool: string;
  /** Run by hand from the Tools tab, or called by the assistant in a chat. */
  trigger: "manual" | "chat";
  thread_id?: string | null;
  actor_email: string;
  args: Record<string, unknown>;
  ok: boolean;
  output: string;
  duration_ms: number;
  created_at: string;
}

export interface ToolRunPage {
  items: ToolRun[];
  total: number;
}
