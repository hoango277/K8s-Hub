"use client";

import { useEffect, useRef } from "react";

import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Hành động không lấy lại được thì để `true` — nút xác nhận sẽ đỏ. */
  nguyHiem?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Hộp thoại xác nhận.
 *
 * Dựng trên thẻ `<dialog>` của trình duyệt chứ không phải một `div` có
 * `position: fixed`. Gọi `showModal()` là được sẵn bốn thứ mà tự làm lại rất
 * dễ thiếu:
 *
 *   - Tiêu điểm bị giữ trong hộp, phím Tab không chạy ra ngoài.
 *   - Esc để đóng.
 *   - Phần còn lại của trang bị ẩn khỏi trình đọc màn hình.
 *   - Lớp nền mờ vẽ ở tầng trên cùng, không phải đấu z-index với ai.
 *
 * Đây là thứ thay cho `window.confirm()`. Hộp thoại của trình duyệt chặn đứng
 * mọi thứ khác trong tab cho tới khi người dùng bấm, và không theo được giao
 * diện của ứng dụng.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Xác nhận",
  cancelLabel = "Huỷ",
  nguyHiem = false,
  onConfirm,
  onCancel,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null);

  // Đồng bộ trạng thái React với thẻ dialog — đây là việc "nói chuyện với một
  // hệ thống bên ngoài", đúng chỗ để dùng effect.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    if (open && !el.open) el.showModal();
    else if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      // Người dùng bấm Esc: trình duyệt tự đóng, phải báo ngược lại cho React
      // biết, nếu không lần mở sau sẽ không ăn.
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      // Bấm ra ngoài hộp thì đóng. Phần nền chính là thẻ dialog, nên nhận được
      // click ở đây nghĩa là click rơi ngoài phần nội dung.
      onClick={(e) => {
        if (e.target === ref.current) onCancel();
      }}
      className={cn(
        "m-auto w-[min(26rem,calc(100vw-2rem))] rounded-xl border p-0",
        "bg-[var(--background)] text-[var(--foreground)] shadow-lg",
      )}
    >
      <div className="p-5">
        <h2 className="text-sm font-semibold">{title}</h2>
        {description && (
          <p className="mt-1.5 text-sm leading-relaxed text-[var(--muted-foreground)]">
            {description}
          </p>
        )}
      </div>

      <div className="flex justify-end gap-2 border-t px-4 py-3">
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border px-3 py-1.5 text-sm transition hover:bg-[var(--accent)]"
        >
          {cancelLabel}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          // Tiêu điểm vào nút này khi mở, nhưng KHÔNG phải nút mặc định của
          // Enter với thao tác nguy hiểm — người dùng phải bấm có chủ đích.
          autoFocus={!nguyHiem}
          className={cn(
            "rounded-md px-3 py-1.5 text-sm font-medium transition hover:opacity-90",
            nguyHiem
              ? "bg-[var(--destructive)] text-[var(--destructive-foreground)]"
              : "bg-[var(--primary)] text-[var(--primary-foreground)]",
          )}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
