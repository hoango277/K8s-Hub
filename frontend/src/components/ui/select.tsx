"use client";

import * as RadixSelect from "@radix-ui/react-select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Ô chọn tự dựng, thay cho `<select>` mặc định của trình duyệt.
 *
 * `<select>` không tạo kiểu được phần danh sách xổ ra — trình duyệt và hệ điều
 * hành tự vẽ, nên nó luôn trông lạc lõng với phần còn lại của giao diện, và
 * không hiện được nhiều dòng thông tin cho mỗi mục.
 *
 * Dựng trên Radix thay vì tự viết từ đầu. Một dropdown "tự viết" nhìn thì
 * giống, nhưng thiếu rất nhiều thứ chỉ lộ ra khi dùng thật: điều hướng bằng
 * phím mũi tên, gõ chữ để nhảy tới mục, Esc để đóng, bẫy tiêu điểm, thông báo
 * cho trình đọc màn hình, và tự lật lên trên khi gần đáy màn hình. Ở đây ô
 * chọn nằm sát đáy khung chat nên chuyện lật hướng xảy ra thường xuyên.
 */

export const Select = RadixSelect.Root;
export const SelectValue = RadixSelect.Value;

export function SelectTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof RadixSelect.Trigger>) {
  return (
    <RadixSelect.Trigger
      className={cn(
        "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5",
        "bg-[var(--background)] text-xs font-medium outline-none transition",
        "hover:border-[var(--ring)] hover:bg-[var(--accent)]",
        "focus-visible:border-[var(--ring)] focus-visible:ring-2 focus-visible:ring-[var(--ring)]",
        "data-[state=open]:border-[var(--ring)] data-[state=open]:bg-[var(--accent)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
      <RadixSelect.Icon asChild>
        <ChevronDown aria-hidden className="size-3.5 shrink-0 opacity-60" />
      </RadixSelect.Icon>
    </RadixSelect.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof RadixSelect.Content>) {
  return (
    <RadixSelect.Portal>
      <RadixSelect.Content
        // "popper" để danh sách bám theo nút và tự lật khi hết chỗ. Kiểu mặc
        // định phủ chồng lên nút, ở sát đáy màn hình sẽ bị che.
        position="popper"
        sideOffset={6}
        collisionPadding={12}
        className={cn(
          "z-50 max-h-[min(24rem,var(--radix-select-content-available-height))]",
          "min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border",
          "bg-[var(--popover)] text-[var(--popover-foreground)] shadow-lg",
          "k8s-xo-xuong",
          className,
        )}
        {...props}
      >
        <RadixSelect.ScrollUpButton className="flex h-6 items-center justify-center bg-[var(--popover)]">
          <ChevronUp aria-hidden className="size-3.5 opacity-60" />
        </RadixSelect.ScrollUpButton>

        <RadixSelect.Viewport className="p-1">{children}</RadixSelect.Viewport>

        <RadixSelect.ScrollDownButton className="flex h-6 items-center justify-center bg-[var(--popover)]">
          <ChevronDown aria-hidden className="size-3.5 opacity-60" />
        </RadixSelect.ScrollDownButton>
      </RadixSelect.Content>
    </RadixSelect.Portal>
  );
}

interface ItemProps extends React.ComponentProps<typeof RadixSelect.Item> {
  /** Dòng phụ nhỏ bên dưới, ví dụ nhà sản xuất và cỡ ngữ cảnh. */
  mota?: React.ReactNode;
}

export function SelectItem({ className, children, mota, ...props }: ItemProps) {
  return (
    <RadixSelect.Item
      className={cn(
        "relative flex cursor-pointer select-none items-start gap-2 rounded-lg",
        "py-1.5 pl-2 pr-2 text-sm outline-none",
        // Radix đánh dấu mục đang trỏ tới bằng data-highlighted — dùng chung
        // cho cả chuột lẫn phím mũi tên, nên không cần xử lý hover riêng.
        "data-[highlighted]:bg-[var(--accent)] data-[highlighted]:text-[var(--accent-foreground)]",
        "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <span className="flex w-4 shrink-0 justify-center pt-0.5">
        <RadixSelect.ItemIndicator>
          <Check aria-hidden className="size-3.5" />
        </RadixSelect.ItemIndicator>
      </span>

      <span className="min-w-0 flex-1">
        <RadixSelect.ItemText>{children}</RadixSelect.ItemText>
        {mota && (
          <span className="mt-0.5 block text-[11px] text-[var(--muted-foreground)]">
            {mota}
          </span>
        )}
      </span>
    </RadixSelect.Item>
  );
}

/** Tiêu đề nhóm trong danh sách. CHƯA DÙNG — để sẵn cho khi gộp model của
    nhiều nhà cung cấp vào chung một danh sách. */
export function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof RadixSelect.Label>) {
  return (
    <RadixSelect.Label
      className={cn(
        "px-2 py-1.5 text-[11px] font-medium uppercase tracking-wide",
        "text-[var(--muted-foreground)]",
        className,
      )}
      {...props}
    />
  );
}
