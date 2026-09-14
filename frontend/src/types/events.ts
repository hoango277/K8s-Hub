/**
 * Sự kiện streaming nhận từ backend qua SSE.
 *
 * ===========================================================================
 *  HỢP ĐỒNG GIỮA BACKEND VÀ FRONTEND
 *  File này phải khớp 1-1 với `backend/app/schemas/events.py`.
 *  Sửa ở đây thì BẮT BUỘC sửa bên kia và báo cả nhóm.
 * ===========================================================================
 *
 * Dùng chung cho hai luồng: hội thoại ra lệnh và tiến trình chẩn đoán.
 */

export type ToolStatus = "ok" | "error";
export type StepStatus = "running" | "done" | "error";
export type DangerLevel = "safe" | "caution" | "dangerous";

/** Phần chung của mọi event. */
export interface BaseEvent {
  /**
   * Số thứ tự tăng dần trong một luồng, bắt đầu từ 1.
   * Dùng để phát hiện mất event và resume sau khi mất kết nối
   * (gửi lại qua header Last-Event-ID).
   */
  seq: number;
}

/** Một mẩu văn bản của câu trả lời. Nối các mẩu lại theo thứ tự. */
export interface TokenEvent extends BaseEvent {
  type: "token";
  content: string;
}

/**
 * Một mẩu SUY LUẬN của mô hình — phần nó tự nghĩ trước khi trả lời.
 *
 * Phải hiển thị tách hẳn khỏi câu trả lời và nhìn ra ngay là suy luận: trong
 * đó có cả phỏng đoán và những kết luận sai mà mô hình tự bác bỏ sau đó.
 * Không phải nhà cung cấp nào cũng gửi loại event này.
 */
export interface ThinkingEvent extends BaseEvent {
  type: "thinking";
  content: string;
}

/**
 * Báo tiến trình một bước xử lý.
 * Nếu `key` trùng với step đã nhận trước đó thì CẬP NHẬT dòng cũ,
 * không thêm dòng mới — nhờ vậy mới đổi được running → done.
 */
export interface StepEvent extends BaseEvent {
  type: "step";
  /** Mã bước, ổn định trong một luồng. VD: "collect_logs" */
  key: string;
  /** Chữ hiển thị cho người dùng */
  label: string;
  status: StepStatus;
}

/** Trợ lý bắt đầu gọi một công cụ. */
export interface ToolCallStartEvent extends BaseEvent {
  type: "tool_call_start";
  /** Mã lần gọi, dùng để ghép với tool_call_end */
  id: string;
  /** Tên công cụ, VD: "list_resources" */
  name: string;
  args: Record<string, unknown>;
}

/** Công cụ chạy xong. `id` trùng với tool_call_start tương ứng. */
export interface ToolCallEndEvent extends BaseEvent {
  type: "tool_call_end";
  id: string;
  status: ToolStatus;
  duration_ms: number;
  /** Kết quả ĐÃ RÚT GỌN để hiển thị. Bản đầy đủ xem trong Langfuse. */
  result?: string;
  /** Chỉ có khi status === "error" */
  error?: string;
}

/** Một bước trong kế hoạch trợ lý đề xuất. */
export interface PlanStep {
  order: number;
  description: string;
}

/** Kế hoạch trợ lý dự định làm, gửi TRƯỚC khi xin duyệt. */
export interface PlanEvent extends BaseEvent {
  type: "plan";
  steps: PlanStep[];
  summary?: string;
}

/**
 * Luồng dừng lại chờ người duyệt.
 * Sau event này luồng SSE KHÔNG kết thúc mà treo chờ.
 * Client gọi POST /approvals/{approval_id}/approve|reject qua request riêng.
 */
export interface ApprovalRequiredEvent extends BaseEvent {
  type: "approval_required";
  approval_id: string;
  /** VD: "Tăng số bản chạy của api từ 1 lên 3" */
  summary: string;
  /** So sánh trước/sau, dạng unified diff YAML */
  diff: string;
  danger_level: DangerLevel;
  /** Kết quả chạy thử không ăn thật */
  dry_run_output?: string;
}

/** Người dùng đã quyết định. Gửi ngay trước khi luồng chạy tiếp. */
export interface ApprovalResolvedEvent extends BaseEvent {
  type: "approval_resolved";
  approval_id: string;
  approved: boolean;
  decided_by?: string;
  /** Lý do khi từ chối */
  reason?: string;
}

/** Kết quả kiểm tra lại sau khi đã thực hiện thao tác lên cụm. */
export interface VerifyResultEvent extends BaseEvent {
  type: "verify_result";
  ok: boolean;
  /** VD: "Đã lên đủ 3/3 bản chạy sau 12 giây" */
  message: string;
}

/** Có lỗi. Nếu retryable === false thì sau event này luồng sẽ kết thúc. */
export interface ErrorEvent extends BaseEvent {
  type: "error";
  /** VD: "llm_timeout", "guardrail_blocked", "k8s_forbidden" */
  code: string;
  message: string;
  retryable: boolean;
}

/** Luồng kết thúc bình thường. Luôn là event cuối cùng. */
export interface DoneEvent extends BaseEvent {
  type: "done";
  /** Id bản ghi trong cơ sở dữ liệu */
  message_id?: string;
  /** Id trace Langfuse, để mở link xem chi tiết */
  trace_id?: string;
}

/**
 * Nhịp giữ kết nối, gửi mỗi ~15 giây khi không có gì để gửi.
 * Không có nó thì proxy sẽ cắt kết nối đang rảnh. Client bỏ qua event này.
 */
export interface HeartbeatEvent extends BaseEvent {
  type: "heartbeat";
}

export type AgentEvent =
  | TokenEvent
  | ThinkingEvent
  | StepEvent
  | ToolCallStartEvent
  | ToolCallEndEvent
  | PlanEvent
  | ApprovalRequiredEvent
  | ApprovalResolvedEvent
  | VerifyResultEvent
  | ErrorEvent
  | DoneEvent
  | HeartbeatEvent;

export type AgentEventType = AgentEvent["type"];

/** Lấy đúng kiểu event theo `type`. VD: `EventOf<"token">` */
export type EventOf<K extends AgentEventType> = Extract<AgentEvent, { type: K }>;

/** Danh sách mọi loại event — dùng để đăng ký listener cho từng loại. */
export const AGENT_EVENT_TYPES = [
  "token",
  "thinking",
  "step",
  "tool_call_start",
  "tool_call_end",
  "plan",
  "approval_required",
  "approval_resolved",
  "verify_result",
  "error",
  "done",
  "heartbeat",
] as const satisfies readonly AgentEventType[];

/**
 * Thu hẹp kiểu khi xử lý event.
 *
 * Khung chat dùng `switch` nên không cần, nhưng màn hình chẩn đoán sắp tới chỉ
 * quan tâm vài loại event — ở đó lọc bằng hàm này gọn hơn.
 */
export function isEvent<K extends AgentEventType>(
  event: AgentEvent,
  type: K,
): event is EventOf<K> {
  return event.type === type;
}

/** Parse `data` của một SSE message. Trả về null nếu không đúng định dạng. */
export function parseAgentEvent(raw: string): AgentEvent | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "type" in parsed &&
      typeof (parsed as { type: unknown }).type === "string" &&
      (AGENT_EVENT_TYPES as readonly string[]).includes(
        (parsed as { type: string }).type,
      )
    ) {
      return parsed as AgentEvent;
    }
    return null;
  } catch {
    return null;
  }
}
