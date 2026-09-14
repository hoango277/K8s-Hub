"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

interface Props {
  /** Phần suy luận đã nhận được cho tới lúc này. */
  content: string;
  /** Còn đang nghĩ hay đã xong. */
  dangNghi: boolean;
  /** Số giây đã nghĩ, chỉ có khi đã xong. */
  giay?: number | null;
}

/**
 * Khối hiển thị phần mô hình tự nghĩ trước khi trả lời.
 *
 * Ba quy tắc, theo đúng thứ tự quan trọng:
 *
 *   1. KHÔNG BAO GIỜ trông giống câu trả lời. Chữ xám, in nghiêng, thụt vào,
 *      có nhãn rõ ràng. Suy luận chứa phỏng đoán và cả những kết luận sai mà
 *      mô hình tự bác bỏ ngay sau đó — người đọc nhầm nó là kết luận thì còn
 *      tệ hơn là không cho xem.
 *   2. Đang nghĩ thì mở, nghĩ xong thì tự thu lại. Lúc chờ, người dùng cần
 *      thấy có gì đó đang diễn ra; lúc đã có câu trả lời, suy luận chỉ làm
 *      rối mắt. Ai muốn xem lại thì bấm mở.
 *   3. Người dùng tự mở/đóng thì tôn trọng lựa chọn đó, không tự động thu nữa.
 */
export function ThinkingBlock({ content, dangNghi, giay = null }: Props) {
  const [mo, setMo] = useState(dangNghi);
  const nguoiDungDaBam = useRef(false);
  const oCuon = useRef<HTMLDivElement>(null);

  // Nghĩ xong thì tự thu lại — trừ khi người dùng đã tự bấm.
  useEffect(() => {
    if (!nguoiDungDaBam.current) setMo(dangNghi);
  }, [dangNghi]);

  // Đang nghĩ thì bám đáy để luôn thấy dòng mới nhất.
  useEffect(() => {
    if (!dangNghi || !mo) return;
    const el = oCuon.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [content, dangNghi, mo]);

  if (!content && !dangNghi) return null;

  const nhan = dangNghi
    ? "Đang suy nghĩ"
    : giay != null
      ? `Đã suy nghĩ trong ${giay.toFixed(1)} giây`
      : "Suy luận của trợ lý";

  return (
    <div className="k8s-hien-len rounded-lg border border-dashed bg-[var(--muted)]/40">
      <button
        type="button"
        onClick={() => {
          nguoiDungDaBam.current = true;
          setMo((v) => !v);
        }}
        aria-expanded={mo}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span aria-hidden className="text-xs text-[var(--muted-foreground)]">
          ✻
        </span>

        <span
          className={cn(
            "text-xs font-medium",
            dangNghi ? "k8s-loe-sang" : "text-[var(--muted-foreground)]",
          )}
        >
          {nhan}
        </span>

        {dangNghi && (
          <span aria-hidden className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="k8s-cham-nay size-1 rounded-full bg-[var(--muted-foreground)]"
                style={{ animationDelay: `${i * 0.16}s` }}
              />
            ))}
          </span>
        )}

        {content && (
          <span className="ml-auto text-xs text-[var(--muted-foreground)]">
            {mo ? "ẩn" : "xem"}
          </span>
        )}
      </button>

      <div className="k8s-mo-ra" data-mo={mo && Boolean(content)}>
        <div>
          <div
            ref={oCuon}
            className={cn(
              "max-h-56 overflow-y-auto whitespace-pre-wrap px-3 pb-3 pl-7",
              "text-xs italic leading-relaxed text-[var(--muted-foreground)]",
            )}
          >
            {content}
          </div>
        </div>
      </div>
    </div>
  );
}
