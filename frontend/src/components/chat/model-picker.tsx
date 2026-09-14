"use client";

import { TriangleAlert } from "lucide-react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { ModelInfo, ProviderInfo } from "@/types/chat";

interface Props {
  provider: string | null;
  model: string | null;
  /** Chỉ gồm nhà cung cấp đã có khoá API — xem `useLuaChonModel`. */
  providers: ProviderInfo[];
  thongTinProvider: ProviderInfo | null;
  danhSachModel: ModelInfo[];
  nguonModel: "api" | "config" | null;
  loiModel: string | null;
  disabled?: boolean;
  onDoiProvider: (ten: string) => void;
  onDoiModel: (ma: string) => void;
}

/** "131K" — dễ đọc hơn 131072 rất nhiều khi liếc qua. */
function coNguCanh(m: ModelInfo): string | null {
  if (!m.context_window) return null;
  const k = Math.round(m.context_window / 1000);
  return k >= 1000 ? `${Math.round(k / 1000)}M ngữ cảnh` : `${k}K ngữ cảnh`;
}

function moTaModel(m: ModelInfo): string {
  return [m.owned_by, coNguCanh(m)].filter(Boolean).join(" · ");
}

export function ModelPicker({
  provider,
  model,
  providers,
  thongTinProvider,
  danhSachModel,
  nguonModel,
  loiModel,
  disabled = false,
  onDoiProvider,
  onDoiModel,
}: Props) {
  if (providers.length === 0) {
    return (
      <p className="flex items-center gap-1.5 px-1 text-xs text-[var(--muted-foreground)]">
        <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
        Chưa có nhà cung cấp nào được điền khoá API. Vào trang Cấu hình để thêm.
      </p>
    );
  }

  const canhBao =
    nguonModel === "config" && loiModel
      ? `Danh sách rút gọn — ${loiModel}`
      : thongTinProvider && !thongTinProvider.supports_tool_calling
        ? "Nhà cung cấp này không gọi được công cụ"
        : null;

  return (
    <div className="flex min-w-0 flex-1 items-center gap-1.5">
      <Select
        value={provider ?? ""}
        onValueChange={onDoiProvider}
        disabled={disabled}
      >
        <SelectTrigger aria-label="Nhà cung cấp" className="shrink-0">
          <SelectValue />
        </SelectTrigger>

        <SelectContent>
          {providers.map((p) => (
            <SelectItem
              key={p.name}
              value={p.name}
              mota={p.supports_tool_calling ? undefined : "không gọi được công cụ"}
            >
              {p.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={model ?? ""}
        onValueChange={onDoiModel}
        disabled={disabled || danhSachModel.length === 0}
      >
        <SelectTrigger
          aria-label="Model"
          // Tên model có thể rất dài; cho co lại và cắt bớt thay vì đẩy nút gửi
          // ra khỏi khung.
          className="min-w-0 max-w-[16rem] flex-1 [&>span]:truncate"
        >
          <SelectValue placeholder="Chọn model" />
        </SelectTrigger>

        <SelectContent className="max-w-[22rem]">
          {danhSachModel.map((m) => (
            <SelectItem key={m.id} value={m.id} mota={moTaModel(m) || undefined}>
              {m.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {canhBao && (
        <span
          title={canhBao}
          className={cn(
            "hidden items-center gap-1 text-xs sm:flex",
            "text-amber-600 dark:text-amber-400",
          )}
        >
          <TriangleAlert aria-hidden className="size-3.5 shrink-0" />
          <span className="max-w-[12rem] truncate">{canhBao}</span>
        </span>
      )}
    </div>
  );
}
