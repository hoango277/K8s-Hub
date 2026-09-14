"use client";

import { Markdown } from "@/components/chat/markdown";
import { ThinkingBlock } from "@/components/chat/thinking-block";
import { ToolCallCard, type ToolCallView } from "@/components/chat/tool-call-card";
import { cn } from "@/lib/utils";
import type { Message } from "@/types/chat";

interface Props {
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCallView[];
  /** Phần mô hình tự nghĩ trước khi trả lời. */
  thinking?: string;
  /** Còn đang nghĩ — hiện hiệu ứng chờ. */
  dangNghi?: boolean;
  /** Số giây đã nghĩ, khi đã xong. */
  giayNghi?: number | null;
  /** Đang nhận chữ — hiện con trỏ nhấp nháy ở cuối. */
  streaming?: boolean;
  error?: string | null;
  meta?: string | null;
}

/** Đổi bản ghi trong CSDL thành dạng thẻ công cụ hiển thị. */
export function toolCallsOf(message: Message): ToolCallView[] {
  return message.tool_calls.map((tc) => ({
    name: tc.name,
    args: tc.args,
    status: tc.status,
    result: tc.result,
    error: tc.error,
    durationMs: tc.duration_ms,
  }));
}

export function MessageItem({
  role,
  content,
  toolCalls = [],
  thinking = "",
  dangNghi = false,
  giayNghi = null,
  streaming = false,
  error = null,
  meta = null,
}: Props) {
  if (role === "user") {
    return (
      <div className="k8s-hien-len flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-sm bg-[var(--primary)] px-4 py-2.5 text-sm text-[var(--primary-foreground)]">
          {content}
        </div>
      </div>
    );
  }

  // Trợ lý đã nhận việc nhưng chưa có gì để hiện: đừng để màn hình đứng im.
  const choTin = streaming && !thinking && !content && toolCalls.length === 0;

  return (
    <div className="space-y-2">
      {(thinking || dangNghi) && (
        <ThinkingBlock content={thinking} dangNghi={dangNghi} giay={giayNghi} />
      )}

      {toolCalls.length > 0 && (
        <div className="space-y-1.5">
          {toolCalls.map((tc, i) => (
            <ToolCallCard key={`${tc.name}-${i}`} call={tc} />
          ))}
        </div>
      )}

      {choTin && (
        <div className="flex items-center gap-2 text-xs">
          <span className="k8s-loe-sang font-medium">Đang kết nối tới trợ lý</span>
          <span aria-hidden className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="k8s-cham-nay size-1 rounded-full bg-[var(--muted-foreground)]"
                style={{ animationDelay: `${i * 0.16}s` }}
              />
            ))}
          </span>
        </div>
      )}

      {content && (
        <Markdown className={cn("break-words", streaming && "k8s-dang-go")}>
          {content}
        </Markdown>
      )}

      {error && (
        <p
          className={cn(
            "k8s-hien-len rounded-md bg-[var(--destructive)]/10 px-3 py-2 text-sm",
            "text-[var(--destructive)]",
          )}
        >
          {error}
        </p>
      )}

      {meta && <p className="text-[11px] text-[var(--muted-foreground)]">{meta}</p>}
    </div>
  );
}
