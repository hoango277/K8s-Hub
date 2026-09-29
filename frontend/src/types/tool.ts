/**
 * Tool catalog and MCP servers — matches backend/app/api/v1/tools.py.
 * Change one side, change the other.
 */

export type ToolCategory = "kubernetes" | "metrics" | "logs" | "traces" | "external";
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
  /** "builtin" or "mcp:<server>". */
  source: string;
  danger: ToolDanger;
  enabled: boolean;
  available: boolean;
  /** Why it can't run right now (disabled, not read-only, backend missing…). */
  unavailable_reason: string | null;
  /** Whether the assistant can call it right now. */
  in_chat: boolean;
  input_schema: JsonSchemaObject;
  /** MCP tools only: what the server CLAIMS — never trusted on its own. */
  read_only_hint: boolean | null;
}

export interface ToolPatch {
  enabled?: boolean;
  /** MCP tools only; built-in danger levels are fixed in code. */
  danger?: ToolDanger;
}

export interface ToolRun {
  id: string;
  tool: string;
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
