"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * Đọc và ghi một giá trị trong localStorage, an toàn với việc dựng trang trên
 * máy chủ.
 *
 * VÌ SAO PHẢI CÓ HOOK NÀY:
 *
 * Trang được dựng sẵn trên máy chủ, nơi không có localStorage. Đọc thẳng lúc
 * dựng thì nội dung máy chủ và trình duyệt lệch nhau, React sẽ báo lỗi hydrate.
 *
 * Cách làm trước đó dùng `useSyncExternalStore` với một hàm `subscribe` rỗng.
 * Nó SAI một cách khó thấy: React lấy giá trị lúc hydrate rồi không đọc lại,
 * mà `subscribe` rỗng thì chẳng bao giờ báo có thay đổi — nên giá trị đã lưu
 * không bao giờ được áp dụng. Chỗ nào tình cờ có thứ khác làm vẽ lại (một truy
 * vấn dữ liệu chẳng hạn) thì vô tình chạy đúng, chỗ nào không có thì hỏng.
 * Thanh điều hướng là chỗ không có, và nó luôn mở lại ở trạng thái mặc định.
 *
 * Ở đây cố tình dựng hai lượt: lượt đầu trả `null` (khớp với máy chủ), gắn vào
 * DOM xong mới đọc giá trị thật. Đúng một lần vẽ thêm, và đó là cái giá bắt
 * buộc phải trả để không lệch hydrate.
 */
export function useLuuTru(khoa: string): [string | null, (giaTri: string) => void] {
  const [giaTri, datGiaTri] = useState<string | null>(null);

  useEffect(() => {
    let daLuu: string | null = null;
    try {
      daLuu = window.localStorage.getItem(khoa);
    } catch {
      // Trình duyệt chặn lưu trữ (cửa sổ ẩn danh, chặn cookie) — coi như chưa
      // có giá trị nào, đừng làm vỡ cả trang.
    }
    if (daLuu === null) return;

    // Đây đúng là trường hợp mà quy tắc dưới đây cho phép: đọc trạng thái từ
    // một hệ thống bên ngoài (localStorage) chỉ tồn tại ở trình duyệt. Chạy
    // đúng một lần cho mỗi khoá, không tạo vòng vẽ lại.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    datGiaTri(daLuu);
  }, [khoa]);

  const luu = useCallback(
    (moi: string) => {
      datGiaTri(moi);
      try {
        window.localStorage.setItem(khoa, moi);
      } catch {
        // Không lưu được thì chỉ mất phần nhớ giữa các lần mở, phiên đang dùng
        // vẫn chạy bình thường.
      }
    },
    [khoa],
  );

  return [giaTri, luu];
}
