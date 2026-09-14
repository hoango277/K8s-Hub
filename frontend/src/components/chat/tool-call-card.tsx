"use client";

import { useState } from "react";

import { cn } from "@/lib/utils";

export interface ToolCallView {
  name: string;
  args: Record<string, unknown>;
  status: "running" | "ok" | "error";
  result?: string | null;
  error?: string | null;
  durationMs?: number | null;
}

const NHAN: Record<ToolCallView["status"], string> = {
  running: "đang chạy",
  ok: "xong",
  error: "lỗi",
};

function thoiGian(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

/** Vòng quay khi công cụ đang chạy, dấu tick/chéo khi xong. */
function DauTrangThai({ status }: { status: ToolCallView["status"] }) {
  if (status === "running") {
    return (
      <span
        aria-hidden
        className={cn(
          "k8s-quay size-3 shrink-0 rounded-full border-[1.5px] border-current",
          "border-t-transparent text-amber-500",
        )}
      />
    );
  }

  return (
    <span
      aria-hidden
      className={cn(
        "flex size-3 shrink-0 items-center justify-center rounded-full text-[8px]",
        "font-bold text-white",
        status === "ok" ? "bg-emerald-500" : "bg-[var(--destructive)]",
      )}
    >
      {status === "ok" ? "✓" : "!"}
    </span>
  );
}

/**
 * Thẻ gấp gọn cho một lần gọi công cụ.
 *
 * Mặc định đóng: người dùng chỉ cần biết trợ lý đã tra gì. Mở ra mới xem tham
 * số và kết quả đầy đủ — đây chính là thứ trả lời câu hỏi "sao nó lại kết luận
 * như vậy".
 */
export function ToolCallCard({ call }: { call: ToolCallView }) {
  const [mo, setMo] = useState(false);
  const coArgs = Object.keys(call.args).length > 0;
  const coChiTiet = coArgs || Boolean(call.result || call.error);

  return (
    <div
      className={cn(
        "k8s-hien-len overflow-hidden rounded-lg border text-sm transition-colors",
        call.status === "error" && "border-[var(--destructive)]/40",
        call.status === "running" && "border-amber-500/40 bg-amber-500/5",
      )}
    >
      <button
        type="button"
        onClick={() => setMo((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        aria-expanded={mo}
      >
        <DauTrangThai status={call.status} />

        <code className="font-medium">{call.name}</code>

        <span className="text-xs text-[var(--muted-foreground)]">
          {NHAN[call.status]}
          {call.durationMs != null && ` · ${thoiGian(call.durationMs)}`}
        </span>

        {coChiTiet && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            {mo ? "thu gọn" : "chi tiết"}
          </span>
        )}
      </button>

      <div className="k8s-mo-ra" data-mo={mo && coChiTiet}>
        <div>
          <div className="space-y-2 border-t px-3 py-2">
            <div>
              <p className="mb-1 text-xs text-[var(--muted-foreground)]">Tham số</p>
              <pre className="overflow-x-auto rounded bg-[var(--muted)] p-2 text-xs">
                {coArgs ? JSON.stringify(call.args, null, 2) : "(không có)"}
              </pre>
            </div>

            {(call.result || call.error) && (
              <div>
                <p className="mb-1 text-xs text-[var(--muted-foreground)]">
                  {call.error ? "Lỗi" : "Kết quả"}
                </p>
                <pre
                  className={cn(
                    "max-h-72 overflow-auto whitespace-pre-wrap rounded p-2 text-xs",
                    call.error
                      ? "bg-[var(--destructive)]/10 text-[var(--destructive)]"
                      : "bg-[var(--muted)]",
                  )}
                >
                  {call.error ?? call.result}
                </pre>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
