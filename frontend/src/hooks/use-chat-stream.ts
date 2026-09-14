"use client";

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { API_BASE } from "@/lib/api";
import { qk } from "@/lib/query-keys";
import { streamAgentEvents } from "@/lib/sse";
import type { AgentEvent } from "@/types/events";

/** Một lần gọi công cụ đang diễn ra, dựng dần từ hai sự kiện start và end. */
export interface LiveToolCall {
  id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  result?: string | null;
  error?: string | null;
  durationMs?: number | null;
}

/** Lượt trao đổi đang chạy — chưa có trong cơ sở dữ liệu. */
export interface LiveTurn {
  /** Câu hỏi vừa gửi, hiện ngay để người dùng thấy phản hồi tức thì. */
  question: string;
  content: string;

  /** Phần mô hình tự nghĩ. Rỗng nếu nhà cung cấp không lộ suy luận. */
  thinking: string;
  /** Tổng thời gian đã nghĩ, tính bằng mili giây. */
  thinkingMs: number;
  /**
   * Mốc bắt đầu đợt nghĩ hiện tại, null nghĩa là đang không nghĩ.
   * Một lượt có thể nghĩ nhiều đợt: nghĩ -> gọi công cụ -> nghĩ tiếp.
   */
  nghiTu: number | null;

  toolCalls: LiveToolCall[];
  status: "streaming" | "error" | "done";
  error: { code: string; message: string; retryable: boolean } | null;
  traceId: string | null;
}

function batDau(question: string): LiveTurn {
  return {
    question,
    content: "",
    thinking: "",
    thinkingMs: 0,
    nghiTu: null,
    toolCalls: [],
    status: "streaming",
    error: null,
    traceId: null,
  };
}

/**
 * Kết thúc đợt suy nghĩ hiện tại và cộng dồn thời gian.
 *
 * Gọi khi có bất cứ dấu hiệu nào cho thấy mô hình đã nghĩ xong: bắt đầu nhả
 * chữ, gọi công cụ, hoặc luồng kết thúc. Không chốt thì dòng "Đang suy nghĩ"
 * sẽ nhấp nháy mãi kể cả khi câu trả lời đã hiện ra.
 */
function chotNghi(t: LiveTurn): LiveTurn {
  if (t.nghiTu === null) return t;
  return { ...t, thinkingMs: t.thinkingMs + (Date.now() - t.nghiTu), nghiTu: null };
}

/**
 * Dựng lại trạng thái của lượt trả lời từ một sự kiện.
 *
 * Tách thành hàm thuần (không đụng React) để dễ theo dõi và test được: cho một
 * chuỗi sự kiện vào, phải ra đúng một trạng thái.
 */
function apDungSuKien(t: LiveTurn, ev: AgentEvent): LiveTurn {
  switch (ev.type) {
    case "thinking":
      return {
        ...t,
        thinking: t.thinking + ev.content,
        nghiTu: t.nghiTu ?? Date.now(),
      };

    case "token":
      return { ...chotNghi(t), content: t.content + ev.content };

    case "tool_call_start":
      return {
        ...chotNghi(t),
        toolCalls: [
          ...t.toolCalls,
          { id: ev.id, name: ev.name, args: ev.args, status: "running" },
        ],
      };

    case "tool_call_end":
      return {
        ...t,
        toolCalls: t.toolCalls.map((tc) =>
          tc.id === ev.id
            ? {
                ...tc,
                status: ev.status,
                result: ev.result,
                error: ev.error,
                durationMs: ev.duration_ms,
              }
            : tc,
        ),
      };

    case "error":
      return {
        ...chotNghi(t),
        status: "error",
        error: { code: ev.code, message: ev.message, retryable: ev.retryable },
      };

    case "done":
      return {
        ...chotNghi(t),
        status: t.status === "error" ? "error" : "done",
        // Backend bỏ hẳn trường null khỏi gói tin, nên ở đây có thể là
        // undefined chứ không chỉ null.
        traceId: ev.trace_id ?? null,
      };

    default:
      // heartbeat, step, plan, approval_*: chưa dùng ở khung chat.
      return t;
  }
}

/**
 * Gửi câu hỏi và dựng lại câu trả lời từ luồng sự kiện.
 *
 * Khi luồng kết thúc, hook nạp lại hội thoại từ máy chủ rồi mới xoá bản đang
 * chạy trên màn hình. Làm ngược lại — xoá trước, nạp sau — sẽ có một khoảnh
 * khắc màn hình trống, nhìn như vừa mất câu trả lời.
 */
export interface LuaChonLLM {
  provider?: string | null;
  model?: string | null;
}

export function useChatStream(threadId: string | null, chon: LuaChonLLM = {}) {
  const qc = useQueryClient();
  const [live, setLive] = useState<LiveTurn | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const dangChay = live?.status === "streaming";

  const send = useCallback(
    async (question: string) => {
      if (!threadId || dangChay) return;

      const controller = new AbortController();
      abortRef.current = controller;
      setLive(batDau(question));

      try {
        for await (const ev of streamAgentEvents(
          `${API_BASE}/chat/threads/${threadId}/stream`,
          // Gửi kèm lựa chọn của người dùng. Bỏ trống thì backend dùng
          // cấu hình hệ thống.
          { content: question, provider: chon.provider, model: chon.model },
          { signal: controller.signal },
        )) {
          setLive((t) => (t ? apDungSuKien(t, ev) : t));
        }
      } catch (err) {
        // Người dùng tự bấm dừng thì không phải lỗi.
        if (!controller.signal.aborted) {
          setLive((t) =>
            t
              ? {
                  ...chotNghi(t),
                  status: "error",
                  error: {
                    code: "network",
                    message:
                      err instanceof Error ? err.message : "Mất kết nối tới máy chủ",
                    retryable: true,
                  },
                }
              : t,
          );
        }
      } finally {
        abortRef.current = null;

        // Máy chủ đã lưu xong (kể cả khi lỗi hoặc bị dừng giữa chừng), nạp lại
        // để màn hình hiện đúng bản trong cơ sở dữ liệu.
        await qc.invalidateQueries({ queryKey: qk.threads.detail(threadId) });
        await qc.invalidateQueries({ queryKey: qk.threads.lists });
        setLive(null);
      }
    },
    [threadId, dangChay, qc, chon.provider, chon.model],
  );

  /** Dừng giữa chừng. Phần trợ lý đã nói vẫn được máy chủ lưu lại. */
  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  return { live, dangChay, send, stop };
}
