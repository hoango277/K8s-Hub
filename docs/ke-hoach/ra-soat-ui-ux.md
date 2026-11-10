# Kế hoạch: rà soát UI/UX toàn trang (11/2026)

*Ngày 10/11/2026, sau khi áp hệ màu theo groq.com (`he-mau-giao-dien.md`). Người dùng duyệt: đổi font, nút bo tròn
kiểu viên thuốc như Groq, và "kiểm tra xem trang web còn chỗ nào có thể cải thiện UI/UX → làm luôn". Đây là
**kế hoạch**; trạng thái chạy thật ghi ở `docs/hien-trang-codebase.md`.*

Cách rà: mở từng trang trong Chrome (đăng nhập sẵn của người dùng) + Playwright không đăng nhập cho trang
Đăng nhập/Đăng ký; chụp màn hình; chạy script kiểm tự động trên trang (nút/link không có tên, ô nhập không có
nhãn, vùng bấm < 24px, cấu trúc tiêu đề); grep mã (`window.confirm`, `alert(`, `<select>` gốc, trang `return
null`, nút tự viết class).

## Tiến độ

| Hạng mục | Trạng thái |
|---|---|
| A. Font Plus Jakarta Sans + JetBrains Mono (có tiếng Việt), nút/chip bo tròn kiểu viên thuốc | **Xong** — cùng ngày đổi tiếp sang Inter + Space Grotesk khi tăng tương phản theo console.groq.com (`he-mau-giao-dien.md`) |
| B. Component dùng chung: `ChipGroup` (bộ lọc), `BackLink` (quay lại), link dạng nút dùng `buttonVariants` | **Xong** |
| C. Chat: nhãn ô nhập, nút xoá hội thoại ≥ 32px, `h1` ẩn, lỗi kỹ thuật cũ → câu dễ hiểu + chi tiết gập lại, thời gian trên danh sách hội thoại | **Xong** |
| D. Hộp thoại "New diagnosis": tên cho công tắc AI report, nhãn gắn với ô chọn | Không cần sửa — kiểm lại mã: đã có `<label htmlFor>` cho công tắc và ô chọn (script báo nhầm vì chưa xét `label[for]` của nút) |
| E. Skills: thẻ skill có nền thẻ (trước lẫn vào nền), mô tả tool dài gập 2 dòng (đo thật, không đoán theo độ dài) | **Xong** — thẻ vốn đã bấm được cả thẻ (`::after` phủ thẻ; script đo nhầm phần chữ) |
| F. Điều hướng con (Skills, Settings): mục đang mở dùng màu nhấn như sidebar | **Xong** |

## Phát hiện

| # | Trang | Vấn đề | Cách sửa |
|---|---|---|---|
| 1 | Chat | Ô nhập tin nhắn chỉ có placeholder, không có nhãn | `aria-label` |
| 2 | Chat | Nút xoá hội thoại 22×22px (quy chuẩn ~32px) | `size-8` |
| 3 | Chat | Không có `h1` (trình đọc màn hình không biết đang ở trang nào) | `h1` ẩn `sr-only` |
| 4 | Chat | Lỗi cũ lưu trong lịch sử hiện nguyên văn kỹ thuật (`RateLimitError: Error code: 429 - {'error': …}`) — trái quy tắc "không lộ chi tiết kỹ thuật thừa" | Câu dễ hiểu theo loại lỗi; nguyên văn trong mục "Details" gập lại |
| 5 | Chat | Nhiều hội thoại cùng tên ("Is everything healthy…") không phân biệt được | Thời gian tương đối dưới tiêu đề |
| 6 | New diagnosis | ~~Công tắc "AI report" không có tên; 3 ô chọn chưa gắn nhãn~~ | Báo nhầm — đã có `<label htmlFor>` |
| 7 | Skills | ~~Chỉ tên skill là link~~ (báo nhầm: link phủ cả thẻ bằng `::after`); thẻ không có nền nên lẫn vào nền giấy | `bg-[var(--card)]` |
| 8 | Tools | Mô tả tool là văn bản viết cho AI, rất dài | Gập 2 dòng, nút "More/Less" |
| 9 | RCA, Skills | Link quay lại cao 20px | `BackLink` dùng chung, vùng bấm 32px |
| 10 | RCA, Approvals, Users | Ba kiểu bộ lọc tự viết khác nhau (`rounded-md`, `radiogroup` thiếu phím mũi tên) | `ChipGroup` dùng chung, chip viên thuốc, `aria-pressed` |
| 11 | Skills, Settings | Mục đang mở của điều hướng con chỉ tô xám, khác sidebar | Chữ màu nhấn |
| 12 | Toàn trang | Nút `rounded-md`, font hệ thống | Viên thuốc, font mới (A) |

Không phát hiện: `window.confirm`/`alert`, `<select>` gốc, trang trống `return null`, tràn ngang ở 420px (trang
Đăng nhập/Đăng ký). Link "Sign up"/"Sign in" nhỏ nhưng nằm trong câu — WCAG 2.5.8 miễn trừ.
