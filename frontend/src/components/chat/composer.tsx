"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import { ArrowUp, Square } from "lucide-react";

import { cn } from "@/lib/utils";

interface Props {
  onSend: (content: string) => void;
  onStop: () => void;
  dangChay: boolean;
  disabled?: boolean;
  placeholder?: string;
  /** Chỗ đặt ô chọn nhà cung cấp và model, nằm trong cùng khung với ô nhập. */
  toolbar?: ReactNode;
}

const CAO_TOI_DA = 200;

/**
 * Ô nhập câu hỏi.
 *
 * Ô nhập, phần chọn model và nút gửi nằm chung MỘT khung có viền, thay vì ba
 * khối rời rạc xếp chồng lên nhau. Chúng luôn được dùng cùng lúc trong một
 * thao tác, nên gom lại thì mắt không phải nhảy qua ba vùng riêng biệt.
 */
export function Composer({
  onSend,
  onStop,
  dangChay,
  disabled = false,
  placeholder = "Hỏi về cụm, hoặc mô tả việc cần làm…",
  toolbar,
}: Props) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  // Ô nhập cao dần theo nội dung, đến một mức thì tự cuộn.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, CAO_TOI_DA)}px`;
  }, [text]);

  const guiDuoc = Boolean(text.trim()) && !disabled && !dangChay;

  function gui() {
    if (!guiDuoc) return;
    onSend(text.trim());
    setText("");
  }

  return (
    <div className="px-4 pb-4 pt-2">
      <div className="mx-auto max-w-3xl">
        <div
          className={cn(
            "rounded-2xl border bg-[var(--background)] shadow-sm transition",
            "focus-within:border-[var(--ring)] focus-within:shadow-md",
          )}
        >
          <textarea
            ref={ref}
            rows={1}
            value={text}
            disabled={disabled}
            placeholder={placeholder}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Enter để gửi, Shift+Enter để xuống dòng. Khi đang gõ tiếng Việt
              // bằng bộ gõ, Enter là để chọn từ — không được cướp phím đó.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                gui();
              }
            }}
            className={cn(
              "w-full resize-none bg-transparent px-4 pt-3 text-sm leading-relaxed",
              "outline-none placeholder:text-[var(--muted-foreground)]",
              "disabled:opacity-50",
            )}
          />

          <div className="flex items-center gap-2 px-2 pb-2 pt-1">
            {toolbar}

            {dangChay ? (
              <button
                type="button"
                onClick={onStop}
                title="Dừng trả lời"
                className={cn(
                  "ml-auto flex size-8 shrink-0 items-center justify-center rounded-full",
                  "border transition hover:bg-[var(--accent)]",
                )}
              >
                <Square aria-hidden className="size-3.5 fill-current" />
                <span className="sr-only">Dừng</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={gui}
                disabled={!guiDuoc}
                title="Gửi (Enter)"
                className={cn(
                  "ml-auto flex size-8 shrink-0 items-center justify-center rounded-full",
                  "bg-[var(--primary)] text-[var(--primary-foreground)] transition",
                  "hover:opacity-90 disabled:opacity-30",
                )}
              >
                <ArrowUp aria-hidden className="size-4" />
                <span className="sr-only">Gửi</span>
              </button>
            )}
          </div>
        </div>

        <p className="mt-1.5 px-1 text-center text-[11px] text-[var(--muted-foreground)]">
          Trợ lý chỉ tra cứu — mọi thay đổi lên cụm đều cần người duyệt.
        </p>
      </div>
    </div>
  );
}
