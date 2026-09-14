"use client";

import { useEffect, useState } from "react";
import { MessageSquarePlus, Trash2 } from "lucide-react";

import { Composer } from "@/components/chat/composer";
import { MessageList } from "@/components/chat/message-list";
import { ModelPicker } from "@/components/chat/model-picker";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useChatStream } from "@/hooks/use-chat-stream";
import { useLuaChonModel } from "@/hooks/use-models";
import {
  useChatTools,
  useCreateThread,
  useDeleteThread,
  useThread,
  useThreads,
} from "@/hooks/use-threads";
import { useLuuTru } from "@/hooks/use-luu-tru";
import { cn } from "@/lib/utils";

/** Khoá lưu hội thoại đang mở, để tải lại trang không mất chỗ đang xem. */
const KHOA_THREAD = "k8shub.thread";

export function ChatPanel() {
  // Hội thoại người dùng vừa bấm chọn trong phiên này.
  const [daBam, setDaBam] = useState<string | null>(null);

  // Hội thoại của lần truy cập trước.
  const [daLuu, luuThread] = useLuuTru(KHOA_THREAD);

  // Hội thoại đang chờ xác nhận xoá.
  const [choXoa, setChoXoa] = useState<string | null>(null);

  const danhSach = useThreads();

  // Hội thoại đang mở được TÍNH RA chứ không lưu thành state riêng.
  //
  // Thứ tự ưu tiên, và `daBam` phải thắng NGAY LẬP TỨC không kèm điều kiện gì:
  // id đó chỉ được đặt khi vừa bấm vào một hội thoại có sẵn, hoặc vừa tạo xong
  // một hội thoại mới — cả hai trường hợp đều chắc chắn tồn tại. Nếu bắt nó
  // phải có mặt trong `danhSach` trước, thì suốt lúc danh sách đang tải lại
  // màn hình sẽ vẫn nằm ở hội thoại cũ — bấm "Hội thoại mới" trông y như
  // không ăn.
  const danhSachData = danhSach.data;
  const threadId =
    daBam ??
    (danhSachData
      ? daLuu && danhSachData.some((t) => t.id === daLuu)
        ? daLuu
        : (danhSachData[0]?.id ?? null)
      : daLuu);

  const chiTiet = useThread(threadId);
  const congCu = useChatTools();
  const taoMoi = useCreateThread();
  const xoa = useDeleteThread();

  const llm = useLuaChonModel();
  const { live, dangChay, send, stop } = useChatStream(threadId, {
    provider: llm.provider,
    model: llm.model,
  });

  useEffect(() => {
    if (threadId && threadId !== daLuu) luuThread(threadId);
  }, [threadId, daLuu, luuThread]);

  async function themHoiThoai() {
    const t = await taoMoi.mutateAsync();
    setDaBam(t.id);
  }

  async function xacNhanXoa() {
    const id = choXoa;
    setChoXoa(null);
    if (!id) return;
    await xoa.mutateAsync(id);
    if (id === daBam) setDaBam(null);
  }

  const tenCongCu = congCu.data?.tools.map((t) => t.name) ?? [];
  const tenChoXoa = danhSachData?.find((t) => t.id === choXoa)?.title ?? "";

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r">
        <div className="p-2">
          <button
            type="button"
            onClick={() => void themHoiThoai()}
            disabled={taoMoi.isPending}
            className={cn(
              "flex h-9 w-full items-center gap-2 rounded-lg border px-3 text-sm",
              "transition hover:bg-[var(--accent)] disabled:opacity-50",
            )}
          >
            <MessageSquarePlus aria-hidden className="size-4 shrink-0" />
            <span>Hội thoại mới</span>
          </button>
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
            {danhSach.isLoading && (
              <p className="px-2 py-1 text-xs text-[var(--muted-foreground)]">
                Đang tải…
              </p>
            )}

            {danhSach.error && (
              <p className="px-2 py-1 text-xs text-[var(--destructive)]">
                Không tải được danh sách. Backend đã chạy chưa?
              </p>
            )}

            {danhSachData?.length === 0 && (
              <p className="px-2 py-1 text-xs text-[var(--muted-foreground)]">
                Chưa có hội thoại nào.
              </p>
            )}

            {danhSachData?.map((t) => (
              <div
                key={t.id}
                className={cn(
                  "group flex items-center rounded-lg transition",
                  t.id === threadId
                    ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                    : "hover:bg-[var(--accent)]/50",
                )}
              >
                <button
                  type="button"
                  onClick={() => setDaBam(t.id)}
                  className="min-w-0 flex-1 px-2.5 py-2 text-left text-sm"
                  title={t.title}
                >
                  <span className="block truncate">{t.title}</span>
                </button>

                <button
                  type="button"
                  onClick={() => setChoXoa(t.id)}
                  aria-label={`Xoá ${t.title}`}
                  title="Xoá hội thoại"
                  className={cn(
                    "mr-1.5 rounded p-1 opacity-0 transition",
                    "hover:text-[var(--destructive)] focus-visible:opacity-100",
                    "group-hover:opacity-100",
                  )}
                >
                  <Trash2 aria-hidden className="size-3.5" />
                </button>
              </div>
            ))}
        </div>
      </aside>

      {/* Khung trò chuyện */}
      <div className="flex min-w-0 flex-1 flex-col">
        {threadId ? (
          <>
            <div className="flex-1 overflow-y-auto">
              {chiTiet.isLoading ? (
                <p className="p-6 text-sm text-[var(--muted-foreground)]">
                  Đang tải hội thoại…
                </p>
              ) : (
                <MessageList
                  messages={chiTiet.data?.messages ?? []}
                  live={live}
                  tenCongCu={tenCongCu}
                />
              )}
            </div>

            <Composer
              onSend={(c) => void send(c)}
              onStop={stop}
              dangChay={dangChay}
              toolbar={
                <ModelPicker
                  provider={llm.provider}
                  model={llm.model}
                  providers={llm.providers}
                  thongTinProvider={llm.thongTinProvider}
                  danhSachModel={llm.danhSachModel}
                  nguonModel={llm.nguonModel}
                  loiModel={llm.loiModel}
                  disabled={dangChay}
                  onDoiProvider={llm.doiProvider}
                  onDoiModel={llm.doiModel}
                />
              }
            />
          </>
        ) : (
          <div className="flex h-full items-center justify-center">
            <button
              type="button"
              onClick={() => void themHoiThoai()}
              className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)]"
            >
              Bắt đầu hội thoại
            </button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={choXoa !== null}
        nguyHiem
        title="Xoá hội thoại này?"
        description={
          tenChoXoa
            ? `“${tenChoXoa}” cùng toàn bộ tin nhắn và lịch sử tra cứu sẽ bị xoá hẳn. Không khôi phục lại được.`
            : "Toàn bộ tin nhắn và lịch sử tra cứu sẽ bị xoá hẳn. Không khôi phục lại được."
        }
        confirmLabel="Xoá"
        onConfirm={() => void xacNhanXoa()}
        onCancel={() => setChoXoa(null)}
      />
    </div>
  );
}
