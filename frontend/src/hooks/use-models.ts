"use client";

import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useLuuTru } from "@/hooks/use-luu-tru";
import { qk } from "@/lib/query-keys";
import type { ModelCatalog, ProvidersView } from "@/types/chat";

const KHOA_LUU = "k8shub.llm";

/** Lựa chọn nhà cung cấp và model của người dùng cho khung chat. */
export interface LuaChon {
  provider: string | null;
  model: string | null;
}

const CHUA_CHON: LuaChon = { provider: null, model: null };

function phanTich(tho: string | null): LuaChon {
  if (!tho) return CHUA_CHON;
  try {
    const d = JSON.parse(tho) as Partial<LuaChon>;
    return {
      provider: typeof d.provider === "string" ? d.provider : null,
      model: typeof d.model === "string" ? d.model : null,
    };
  } catch {
    // Dữ liệu cũ hỏng định dạng — coi như chưa chọn, đừng làm vỡ cả trang.
    return CHUA_CHON;
  }
}

export function useProviders() {
  return useQuery({
    queryKey: qk.chat.providers,
    queryFn: () => api.get<ProvidersView>("/chat/providers"),
    staleTime: 5 * 60 * 1000,
  });
}

export function useModels(provider: string | null) {
  return useQuery({
    queryKey: qk.chat.models(provider ?? ""),
    queryFn: () => api.get<ModelCatalog>(`/chat/models?provider=${provider}`),
    enabled: Boolean(provider),
    // Backend đã nhớ đệm 10 phút và không bao giờ trả lỗi, nên đừng hỏi lại
    // mỗi lần quay về tab.
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

/**
 * Quản lý lựa chọn nhà cung cấp + model cho khung chat.
 *
 * Lựa chọn được nhớ trong trình duyệt. Chưa chọn gì thì dùng cấu hình hệ
 * thống — nghĩa là người dùng không phải đụng vào hai ô này vẫn chat được.
 */
export function useLuaChonModel() {
  const qc = useQueryClient();
  const providers = useProviders();

  // Lựa chọn đã lưu trong trình duyệt. Ghi vào đây cũng cập nhật luôn state,
  // nên người dùng vừa đổi là thấy đổi ngay.
  const [tho, luuTho] = useLuuTru(KHOA_LUU);
  const luaChon = useMemo(() => phanTich(tho), [tho]);

  // Chỉ hiện nhà cung cấp đã điền khoá API. Cho chọn một nhà cung cấp chắc
  // chắn không chạy được là bẫy người dùng: lỗi chỉ lộ ra sau khi họ đã gõ
  // xong câu hỏi và bấm gửi.
  const coSan = useMemo(
    () => (providers.data?.providers ?? []).filter((p) => p.api_key_set),
    [providers.data],
  );

  const macDinh = providers.data?.current.provider ?? null;

  // Nhà cung cấp đang chọn phải nằm trong số dùng được. Cấu hình hệ thống trỏ
  // vào một nhà cung cấp chưa có khoá thì rơi về cái đầu tiên dùng được.
  const provider =
    [luaChon.provider, macDinh].find((t) => t && coSan.some((p) => p.name === t)) ??
    coSan[0]?.name ??
    null;

  const models = useModels(provider);

  // Model đang chọn phải thuộc về nhà cung cấp đang chọn. Sau khi đổi nhà cung
  // cấp, model cũ không còn hợp lệ nên phải bỏ đi.
  const danhSach = models.data?.models ?? [];
  const modelHopLe =
    luaChon.model && danhSach.some((m) => m.id === luaChon.model)
      ? luaChon.model
      : null;

  const thongTinProvider = coSan.find((p) => p.name === provider) ?? null;

  /** Chỉ nhận model nếu nó thật sự có trong danh sách đang hiện.
   *
   * Ô chọn nhận một giá trị không khớp mục nào sẽ hiện trống trơn, mà người
   * dùng vẫn bấm gửi được — rồi nhận lỗi từ nhà cung cấp. */
  const coTrongDanhSach = (ma: string | null | undefined) =>
    ma && danhSach.some((m) => m.id === ma) ? ma : null;

  const model =
    modelHopLe ??
    // Đúng nhà cung cấp hệ thống đang đặt thì theo model hệ thống đang đặt.
    (provider === macDinh ? coTrongDanhSach(providers.data?.current.model) : null) ??
    // Nhà cung cấp khác: lấy model mặc định CỦA NÓ.
    //
    // Không có bước này thì rơi xuống phần tử đầu danh sách đã sắp theo bảng
    // chữ cái — với Google là "antigravity-preview", một model nghiên cứu
    // chậm và đắt. Chọn mặc định phải là model dùng hàng ngày.
    coTrongDanhSach(thongTinProvider?.default_model) ??
    danhSach[0]?.id ??
    null;

  const luu = useCallback(
    (moi: LuaChon) => luuTho(JSON.stringify(moi)),
    [luuTho],
  );

  const doiProvider = useCallback(
    (ten: string) => {
      // Bỏ model cũ: nó thuộc nhà cung cấp khác.
      luu({ provider: ten, model: null });
      void qc.prefetchQuery({
        queryKey: qk.chat.models(ten),
        queryFn: () => api.get<ModelCatalog>(`/chat/models?provider=${ten}`),
      });
    },
    [luu, qc],
  );

  const doiModel = useCallback(
    (ma: string) => luu({ provider, model: ma }),
    [luu, provider],
  );

  return {
    provider,
    model,
    providers: coSan,
    thongTinProvider,
    danhSachModel: danhSach,
    nguonModel: models.data?.source ?? null,
    loiModel: models.data?.error ?? null,
    dangTai: providers.isLoading || models.isLoading,
    doiProvider,
    doiModel,
  };
}
