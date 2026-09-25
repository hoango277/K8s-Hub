/**
 * Conversation data read from the backend.
 *
 * Matches `backend/app/schemas/chat.py`. Change one side, change the other.
 *
 * Contrast with `types/events.ts`: that file is what FLOWS THROUGH while the
 * assistant is running; this file is what can be READ BACK afterwards from
 * the database.
 */

export type MessageRole = "user" | "assistant" | "system";
export type MessageStatus = "streaming" | "complete" | "error";
export type ToolCallStatus = "running" | "ok" | "error";

export interface Thread {
  id: string;
  title: string;
  cluster: string | null;
  archived: boolean;
  created_at: string;
  last_message_at: string | null;
}

export interface ToolCall {
  id: string;
  call_id: string;
  name: string;
  args: Record<string, unknown>;
  result: string | null;
  status: ToolCallStatus;
  error: string | null;
  duration_ms: number | null;
  started_at: string;
}

export interface Message {
  id: string;
  thread_id: string;
  role: MessageRole;
  content: string;

  /** The model's own reasoning. null if the provider doesn't expose it. */
  reasoning: string | null;

  position: number;
  status: MessageStatus;
  error: string | null;
  created_at: string;
  trace_id: string | null;
  provider: string | null;
  model: string | null;
  latency_ms: number | null;

  /** Tokens spent. null for user messages. */
  prompt_tokens: number | null;
  completion_tokens: number | null;

  tool_calls: ToolCall[];
}

export interface ThreadDetail extends Thread {
  messages: Message[];
}

/** Request body sent to `POST /chat/threads/{id}/stream`. */
export interface ChatRequest {
  content: string;
  provider?: string | null;
  model?: string | null;
}

export interface ToolInfo {
  name: string;
  description: string;
}

/** An LLM provider declared on the backend. */
export interface ProviderInfo {
  name: string;
  api_key_set: boolean;
  api_key_field: string;
  supports_tool_calling: boolean;
  /** This provider's OWN default model. */
  default_model: string;
  fast_model: string;
  notes: string;
}

export interface ProvidersView {
  providers: ProviderInfo[];
  /** The system's current choice, used when the user hasn't picked anything. */
  current: { provider: string; model: string };
}

export interface ModelInfo {
  id: string;
  label: string;
  context_window: number | null;
  owned_by: string | null;
}

export interface ModelCatalog {
  provider: string;
  models: ModelInfo[];
  /** 'api' = the provider was queried, 'config' = fell back to preconfigured models. */
  source: "api" | "config";
  /** Why the provider couldn't be queried. When set, source='config'. */
  error: string | null;
}
