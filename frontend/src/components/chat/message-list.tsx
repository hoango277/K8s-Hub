"use client";

import { useEffect, useRef } from "react";

import { MessageItem, toolCallsOf } from "@/components/chat/message-item";
import type { LiveTurn } from "@/hooks/use-chat-stream";
import type { Message } from "@/types/chat";

interface Props {
  messages: Message[];
  live: LiveTurn | null;
  tenCongCu: string[];
}

function chuThich(m: Message): string | null {
  if (m.role !== "assistant") return null;
  const phan: string[] = [];
  if (m.model) phan.push(m.model);
  if (m.latency_ms != null) phan.push(`${(m.latency_ms / 1000).toFixed(1)}s`);
  return phan.length ? phan.join(" · ") : null;
}

export function MessageList({ messages, live, tenCongCu }: Props) {
  const dayRef = useRef<HTMLDivElement>(null);

  // Luôn bám đáy khi có chữ mới. Dùng chiều dài nội dung làm phụ thuộc để mỗi
  // mẩu chữ nhận được đều kéo màn hình xuống theo.
  useEffect(() => {
    dayRef.current?.scrollIntoView({ block: "end" });
  }, [
    messages.length,
    live?.content.length,
    live?.thinking.length,
    live?.toolCalls.length,
  ]);

  const trong = messages.length === 0 && !live;

  if (trong) {
    return (
      <div className="flex h-full items-center justify-center px-6">
        <div className="max-w-md text-center">
          <h2 className="text-lg font-medium">Bắt đầu một hội thoại</h2>
          <p className="mt-2 text-sm text-[var(--muted-foreground)]">
            Hỏi về tình trạng cụm, nguyên nhân một sự cố, hoặc mô tả thao tác
            bạn muốn thực hiện.
          </p>
          {tenCongCu.length > 0 && (
            <p className="mt-4 text-xs text-[var(--muted-foreground)]">
              Công cụ đang có:{" "}
              {tenCongCu.map((t) => (
                <code key={t} className="mx-0.5 rounded bg-[var(--muted)] px-1 py-0.5">
                  {t}
                </code>
              ))}
            </p>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      {messages.map((m) => (
        <MessageItem
          key={m.id}
          role={m.role}
          content={m.content}
          thinking={m.reasoning ?? ""}
          toolCalls={toolCallsOf(m)}
          error={m.status === "error" ? m.error : null}
          meta={chuThich(m)}
        />
      ))}

      {live && (
        <>
          <MessageItem role="user" content={live.question} />
          <MessageItem
            role="assistant"
            content={live.content}
            thinking={live.thinking}
            dangNghi={live.nghiTu !== null}
            giayNghi={live.thinkingMs > 0 ? live.thinkingMs / 1000 : null}
            toolCalls={live.toolCalls}
            streaming={live.status === "streaming"}
            error={live.error?.message ?? null}
          />
        </>
      )}

      <div ref={dayRef} />
    </div>
  );
}
