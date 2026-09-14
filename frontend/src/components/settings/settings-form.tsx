"use client";

import { useMemo, useState } from "react";

import { FieldInput } from "@/components/settings/field-input";
import { useReloadEnv, useResetSettings, useSettings, useUpdateSettings } from "@/hooks/use-settings";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/utils";
import { GROUP_ORDER, groupOf, NGUY_HIEM, type SettingField } from "@/types/settings";

/** Giá trị đang hiển thị cho một trường: đã sửa thì lấy bản nháp, chưa thì lấy từ máy chủ. */
type Draft = Record<string, unknown>;

function hienThi(field: SettingField): unknown {
  // Bí mật không bao giờ được máy chủ trả giá trị về.
  return field.secret ? "" : field.value;
}

function bangNhau(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function SettingsForm() {
  const { data, isLoading, error } = useSettings();
  const capNhat = useUpdateSettings();
  const datLai = useResetSettings();
  const napLai = useReloadEnv();

  const [draft, setDraft] = useState<Draft>({});
  const [thongBao, setThongBao] = useState<string | null>(null);

  const daSua = useMemo(() => {
    if (!data) return [] as string[];
    return Object.keys(draft).filter((name) => {
      const field = data.fields.find((f) => f.name === name);
      if (!field) return false;
      // Với bí mật, chỉ tính là sửa khi người dùng gõ gì đó.
      if (field.secret) return typeof draft[name] === "string" && draft[name] !== "";
      return !bangNhau(draft[name], field.value);
    });
  }, [draft, data]);

  const dangGui = capNhat.isPending || datLai.isPending || napLai.isPending;
  const loiGui = capNhat.error instanceof ApiError ? capNhat.error.message : null;

  function datGiaTri(name: string, value: unknown) {
    setDraft((d) => ({ ...d, [name]: value }));
    setThongBao(null);
    capNhat.reset();
  }

  function huyBo() {
    setDraft({});
    setThongBao(null);
    capNhat.reset();
  }

  async function luu() {
    if (!data || daSua.length === 0) return;

    const values: Record<string, unknown> = {};
    for (const name of daSua) {
      const field = data.fields.find((f) => f.name === name)!;
      let value = draft[name];

      // Ô JSON được gõ dạng chữ, phải parse trước khi gửi.
      if (field.type === "object" && typeof value === "string") {
        try {
          value = value.trim() === "" ? {} : JSON.parse(value);
        } catch {
          setThongBao(`${field.name}: không phải JSON hợp lệ`);
          return;
        }
      }
      values[name] = value;
    }

    try {
      await capNhat.mutateAsync({ values });
      setDraft({});
      setThongBao(`Đã lưu ${daSua.length} thay đổi`);
    } catch {
      /* lỗi hiển thị qua capNhat.error */
    }
  }

  async function khoiPhuc(field: SettingField) {
    // Gửi null để backend bỏ ghi đè, trả về giá trị trong .env.
    await capNhat.mutateAsync({ values: { [field.name]: null } });
    setDraft((d) => {
      const { [field.name]: _bo, ...con } = d;
      return con;
    });
    setThongBao(`Đã khôi phục ${field.name} về giá trị trong .env`);
  }

  if (isLoading) {
    return <p className="p-8 text-sm text-[var(--muted-foreground)]">Đang tải cấu hình…</p>;
  }

  if (error || !data) {
    return (
      <div className="m-8 rounded-lg border border-[var(--destructive)] p-4 text-sm">
        <p className="font-medium text-[var(--destructive)]">Không tải được cấu hình</p>
        <p className="mt-1 text-[var(--muted-foreground)]">
          {error instanceof Error ? error.message : "Lỗi không xác định"}
        </p>
      </div>
    );
  }

  const theoNhom = GROUP_ORDER.map((g) => ({
    ten: g,
    fields: data.fields.filter((f) => groupOf(f.name) === g),
  })).filter((g) => g.fields.length > 0);

  return (
    <div className="mx-auto max-w-4xl px-6 pb-32 pt-8">
      <header className="mb-8">
        <h1 className="text-2xl font-semibold">Cấu hình hệ thống</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          Thay đổi ở đây có hiệu lực ngay, không cần khởi động lại. Giá trị gốc nằm trong
          file <code className="rounded bg-[var(--muted)] px-1 py-0.5 text-xs">.env</code>.
        </p>
      </header>

      {theoNhom.map((nhom) => (
        <section key={nhom.ten} className="mb-10">
          <h2 className="mb-4 text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
            {nhom.ten}
          </h2>

          <div className="divide-y rounded-lg border">
            {nhom.fields.map((field) => {
              const coNhap = field.name in draft;
              const value = coNhap ? draft[field.name] : hienThi(field);
              const daDoi = daSua.includes(field.name);
              const canhBao =
                NGUY_HIEM[field.name]?.includes(String(value)) ?? false;

              return (
                <div key={field.name} className="grid gap-3 p-4 sm:grid-cols-[1fr_20rem]">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <code className="text-sm font-medium">{field.name}</code>
                      {field.overridden && (
                        <span className="rounded-full bg-[var(--accent)] px-2 py-0.5 text-[11px] text-[var(--accent-foreground)]">
                          đang ghi đè
                        </span>
                      )}
                      {daDoi && (
                        <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-[11px] text-amber-600 dark:text-amber-400">
                          chưa lưu
                        </span>
                      )}
                    </div>

                    {field.description && (
                      <p className="mt-1 text-xs leading-relaxed text-[var(--muted-foreground)]">
                        {field.description}
                      </p>
                    )}

                    {field.overridden && !field.secret && (
                      <button
                        type="button"
                        onClick={() => void khoiPhuc(field)}
                        disabled={dangGui}
                        className="mt-1.5 text-xs text-[var(--muted-foreground)] underline underline-offset-2 hover:text-[var(--foreground)] disabled:opacity-50"
                      >
                        Khôi phục về {JSON.stringify(field.env_value)}
                      </button>
                    )}

                    {canhBao && (
                      <p className="mt-2 rounded-md bg-[var(--destructive)]/10 px-2 py-1.5 text-xs text-[var(--destructive)]">
                        Chế độ này cho phép AI tự thực hiện thao tác lên cụm mà không cần người
                        duyệt. Chỉ dùng trên cụm thử nghiệm.
                      </p>
                    )}
                  </div>

                  <div className="sm:pt-0.5">
                    <FieldInput
                      field={field}
                      value={value}
                      onChange={(v) => datGiaTri(field.name, v)}
                    />
                    {field.secret && field.is_set && (
                      <p className="mt-1 text-[11px] text-[var(--muted-foreground)]">
                        Đã có khoá. Để trống nếu không muốn đổi.
                      </p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ))}

      {/* Thanh hành động dính đáy màn hình */}
      <div className="fixed inset-x-0 bottom-0 border-t bg-[var(--background)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-4xl flex-wrap items-center gap-3 px-6 py-3">
          <button
            type="button"
            onClick={() => void luu()}
            disabled={daSua.length === 0 || dangGui}
            className="rounded-md bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:opacity-40"
          >
            {capNhat.isPending ? "Đang lưu…" : `Lưu${daSua.length ? ` (${daSua.length})` : ""}`}
          </button>

          <button
            type="button"
            onClick={huyBo}
            disabled={daSua.length === 0 || dangGui}
            className="rounded-md border px-4 py-2 text-sm transition hover:bg-[var(--accent)] disabled:opacity-40"
          >
            Huỷ
          </button>

          <div className="ml-auto flex items-center gap-3">
            <button
              type="button"
              onClick={() => void napLai.mutateAsync()}
              disabled={dangGui}
              title="Đọc lại file .env từ đĩa, giữ nguyên phần đã đổi ở đây"
              className="text-sm text-[var(--muted-foreground)] underline underline-offset-2 hover:text-[var(--foreground)] disabled:opacity-40"
            >
              Đọc lại .env
            </button>

            <button
              type="button"
              onClick={() => {
                if (confirm("Bỏ hết thay đổi và quay về đúng file .env?")) {
                  void datLai.mutateAsync().then(() => setDraft({}));
                }
              }}
              disabled={Object.keys(data.overrides).length === 0 || dangGui}
              className="text-sm text-[var(--destructive)] underline underline-offset-2 disabled:opacity-40"
            >
              Đặt lại tất cả
            </button>
          </div>
        </div>

        {(loiGui || thongBao) && (
          <div
            className={cn(
              "border-t px-6 py-2 text-sm",
              loiGui
                ? "bg-[var(--destructive)]/10 text-[var(--destructive)]"
                : "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
            )}
          >
            <div className="mx-auto max-w-4xl">{loiGui ?? thongBao}</div>
          </div>
        )}
      </div>
    </div>
  );
}
