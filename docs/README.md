# Tài liệu K8s-Hub — đọc ở đây trước

Thư mục này là **điểm bắt đầu** khi đọc dự án (người hay AI). Đọc theo thứ tự:

1. **`hien-trang-codebase.md`** — những gì *đang thực sự chạy* trong kho mã. Nguồn sự thật duy nhất về
   hiện trạng; README ở gốc kho chỉ mô tả kế hoạch ban đầu.
2. **`ke-hoach/`** — kế hoạch các phần đang làm hoặc sắp làm, mỗi file có bảng "Tiến độ" ở đầu.
3. `../CLAUDE.md` — quy tắc thường trực (ngôn ngữ, UI/UX, phân quyền, phê duyệt, giám sát).

| File | Nội dung | Trạng thái |
|---|---|---|
| [hien-trang-codebase.md](hien-trang-codebase.md) | Báo cáo hiện trạng, 7 mục | cập nhật sau mỗi thay đổi mã |
| [ke-hoach/rca-groot.md](ke-hoach/rca-groot.md) | RCA kiểu Groot: cơ chế, thiết kế, giai đoạn, đánh giá, nguồn dữ liệu quan sát | đủ 6 giai đoạn; đánh giá 8 kịch bản top-1 8/8 |
| [ke-hoach/rca-cai-tien.md](ke-hoach/rca-cai-tien.md) | Cải tiến RCA: toàn cụm, đồ thị gọi đa nguồn, thêm nguồn thay đổi, học từ phản hồi, phát hiện bất thường | xong 1–5 (08/10/2026) |
| [ke-hoach/bao-mat-llm.md](ke-hoach/bao-mat-llm.md) | Bảo mật request cho LLM: chống prompt injection gián tiếp (chat + RCA), bộ đo trước/sau | 0–5, 7 xong (09/10/2026); 6 chờ kubeconfig lab1 |
| [ke-hoach/he-mau-giao-dien.md](ke-hoach/he-mau-giao-dien.md) | Hệ màu giao diện: tra cứu (Geist, Radix, Primer, Atlassian, Carbon, 60-30-10), mẫu groq.com, quy tắc, token | xong (10/11/2026) |
| [ke-hoach/ra-soat-ui-ux.md](ke-hoach/ra-soat-ui-ux.md) | Rà soát UI/UX toàn trang: font, nút viên thuốc, component dùng chung, chat, skills, điều hướng con | xong (10/11/2026) |
| [ke-hoach/noi-rca-chat-skills.md](ke-hoach/noi-rca-chat-skills.md) | Nối RCA với Chat và Skills: "Ask in chat" có ngữ cảnh, tool `get_diagnosis`, skill gợi ý theo loại sự kiện | xong (10/11/2026) |
| [ke-hoach/hoan-tac-thay-doi.md](ke-hoach/hoan-tac-thay-doi.md) | Hoàn tác thay đổi đã chạy: lưu trạng thái trước, đề xuất ngược qua phê duyệt | xong, đã chạy thật trên lab1 (10/11/2026) |
| [rca-tong-ket.md](rca-tong-ket.md) | Tổng kết RCA: kết quả 8 kịch bản, so sánh k8sgpt / agent LLM / Groot…, hạn chế, hướng cải thiện | 07/10/2026 |
| `ke-hoach-*.xlsx` | Kế hoạch đồ án/backend 8 tuần (tháng 9/2026) | tham khảo, có thể lạc hậu |

Quy ước:
- Kế hoạch mới (kể cả kế hoạch viết ở chế độ plan của Claude Code) phải được lưu vào `ke-hoach/<chu-de>.md`
  trước khi bắt đầu làm, và cập nhật bảng "Tiến độ" khi xong từng giai đoạn.
- Kế hoạch nói điều *định làm*; `hien-trang-codebase.md` nói điều *đã có*. Đừng chép trạng thái chạy thật
  vào kế hoạch thay cho báo cáo hiện trạng.
- Tài liệu trong `docs/` viết tiếng Việt; mã nguồn và giao diện viết tiếng Anh (xem `CLAUDE.md`).
