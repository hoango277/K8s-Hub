/**
 * Dữ liệu hội thoại đọc từ backend.
 *
 * Khớp với `backend/app/schemas/chat.py`. Sửa một bên thì phải sửa bên kia.
 *
 * Phân biệt với `types/events.ts`: file đó là những gì CHẢY QUA khi trợ lý
 * đang chạy; file này là những gì ĐỌC LẠI ĐƯỢC sau đó từ cơ sở dữ liệu.
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

  /** Phần mô hình tự nghĩ. null nếu nhà cung cấp không lộ suy luận. */
  reasoning: string | null;

  position: number;
  status: MessageStatus;
  error: string | null;
  created_at: string;
  trace_id: string | null;
  provider: string | null;
  model: string | null;
  latency_ms: number | null;
  tool_calls: ToolCall[];
}

export interface ThreadDetail extends Thread {
  messages: Message[];
}

/** Thân request gửi tới `POST /chat/threads/{id}/stream`. */
export interface ChatRequest {
  content: string;
  provider?: string | null;
  model?: string | null;
}

export interface ToolInfo {
  name: string;
  description: string;
}

/** Một nhà cung cấp LLM đang được khai báo ở backend. */
export interface ProviderInfo {
  name: string;
  api_key_set: boolean;
  api_key_field: string;
  supports_tool_calling: boolean;
  /** Model mặc định CỦA RIÊNG nhà cung cấp này. */
  default_model: string;
  fast_model: string;
  notes: string;
}

export interface ProvidersView {
  providers: ProviderInfo[];
  /** Lựa chọn hệ thống đang đặt, dùng khi người dùng chưa chọn gì. */
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
  /** 'api' = hỏi được nhà cung cấp, 'config' = phải dùng model khai sẵn. */
  source: "api" | "config";
  /** Lý do không hỏi được nhà cung cấp. Có giá trị thì source='config'. */
  error: string | null;
}
