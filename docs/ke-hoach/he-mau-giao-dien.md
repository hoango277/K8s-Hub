# Kế hoạch: hệ màu giao diện

*Ngày 10/11/2026. Bối cảnh: người dùng thấy giao diện đen–trắng "khó nhìn", muốn chỗ cần để ý phải nổi lên.
Lần thử đầu đổi màu chủ đạo sang **xanh dương** cho cả trang bị chê "không đẹp" (xanh tràn khắp nơi). Người
dùng yêu cầu tra bảng màu các sản phẩm tech hay dùng để rút quy tắc, rồi chỉ **[groq.com/platform](https://groq.com/platform)
làm mẫu** ("rất đẹp"). Đây là **kế hoạch + quy tắc**; trạng thái chạy thật ghi ở `docs/hien-trang-codebase.md`.*

## Tiến độ

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Tra cứu + quy tắc | **Xong** (10/11/2026) | Mục 1–2; tóm tắt trong `CLAUDE.md` mục "Quy chuẩn giao diện" |
| Bảng màu theo groq.com | **Xong** | Mục 3; màu đọc thẳng từ CSS của groq.com |
| Token (`globals.css`) + tiện ích `eyebrow` | **Xong** | |
| Component dùng chung (layout, sidebar, header, PageHeader, EmptyState, Badge, Button, toast) | **Xong** | |
| Trang: RCA, Approvals/thẻ phê duyệt, chat, skills/tools, users, settings, account | **Xong** | Thay màu cứng bằng token; nhấn chỗ cần để ý |
| Font + nút viên thuốc giống Groq | **Xong** (10/11/2026) | Lần đầu: Plus Jakarta Sans + JetBrains Mono; nút/chip `rounded-full`. Chi tiết ở `ra-soat-ui-ux.md` |
| Tăng tương phản theo console.groq.com | **Xong** (10/11/2026) | Người dùng vẫn thấy "mọi thứ khó nhìn", chỉ trang [console.groq.com/home](https://console.groq.com/home) làm mẫu ("đậm hơn"). Nền giấy be → gần trắng, chữ nâu → gần đen, chữ phụ 5:1 → 7,6:1, viền ô nhập/nút đậm hơn; font → Inter + Space Grotesk (đúng bộ của console). Mục 1 (dòng console), mục 2 (quy tắc 1, 7, 9), mục 3 |

## 1. Tra cứu: các hệ thiết kế dùng màu thế nào

| Nguồn | Điều rút ra |
|---|---|
| [Vercel Geist](https://vercel.com/design.md) | Nền canvas trắng ngà, chữ và nút chính gần đen, **viền mảnh tạo cấu trúc thay bóng đổ**, chữ phụ là các bậc xám; đỏ chỉ cho lỗi. |
| [Radix Colors](https://www.radix-ui.com/colors/docs/palette-composition/understanding-the-scale) | Mỗi thang 12 bậc có vai trò cố định: nền app, nền component, viền, nền đặc, chữ — chữ bậc 11–12 đạt 4,5:1 trên nền bậc 3. |
| [GitHub Primer](https://primer.style/foundations/color/overview) | Màu theo **vai trò** (accent, success, attention, danger…), mỗi vai trò có chữ, *muted* (nền/viền nhạt) và *emphasis* (nền đặc). Không dùng chữ xám trên nền màu. |
| [Atlassian](https://atlassian.design/foundations/color) | 4 mức nhấn nền; **không dùng màu nhấn cho thứ có nghĩa ngữ nghĩa**; viền cần 3:1. |
| [IBM Carbon](https://carbondesignsystem.com/patterns/status-indicator-pattern) | 4 trạng thái: đỏ lỗi, vàng/cam cảnh báo, xanh lá thành công, xanh dương thông tin — luôn kèm icon. |
| [SAP Fiori](https://www.sap.com/design-system/fiori-design-web/v1-136/foundations/best-practices/ui-elements/how-to-use-semantic-colors) | Chỉ dùng màu ngữ nghĩa khi đúng nghĩa, **không để trang trí**; luôn kèm chữ. |
| [Quy tắc 60-30-10](https://blog.logrocket.com/ux-design/60-30-10-rule) | 60% nền trung tính, 30% bề mặt phụ, 10% màu nhấn. Lỗi phổ biến nhất: **lạm dụng màu nhấn** — đúng lỗi của lần đổi sang xanh dương. App nhiều dữ liệu: ~90% trung tính, 3–5 chỗ nhấn mỗi màn hình. |
| [Linear](https://linear.app/now/how-we-redesigned-the-linear-ui), Stripe, Vercel | Mỗi hãng **một màu nhấn**; Linear dựng theme từ 3 biến (nền, nhấn, tương phản). |
| **[groq.com](https://groq.com/platform)** (mẫu người dùng chọn) | Nền "giấy" ấm `#f3f3ee`, chữ "mực" nâu-đen `#302b28`, chữ phụ `#69695d`; **một màu cam** `#f43e01` cho logo, mục nav đang mở (chữ cam + gạch chân), nút (viền cam, bo tròn hẳn), nhãn pill; **lỗi là đỏ hồng `#f80a3e`, tách khỏi cam**; màu phụ ô-liu `#475c05`; đường kẻ mảnh chia ô, không bóng đổ; nhãn nhỏ viết hoa font mono giãn chữ ("PLATFORM", "INFRASTRUCTURE"); tiêu đề lớn, chữ khít. |
| **[console.groq.com](https://console.groq.com/home)** (mẫu thứ hai, "đậm hơn") | Đo bằng `getComputedStyle` (trang công khai, không đăng nhập): nền `#ffffff`, thanh trên `#fafafa`, thẻ trắng viền `#e7e5e4` (bảng màu *stone* của Tailwind); chữ thân **`#0c0a09`** (gần đen), tiêu đề `#1e1e1e`, chữ phụ nâu-xám `#655852`/`#766f6b`; **Inter** cho chữ thường (nút 14px/500), **Space Grotesk** cho tiêu đề, menu, nhãn nhóm viết hoa 13px/500; cam `#f55036` cho link. Khác groq.com chủ yếu ở chỗ bỏ nền giấy be — nên đọc rõ hơn hẳn. |

## 2. Quy tắc (mọi trang)

1. **Trung tính ~90%, tương phản cao** (theo console.groq.com): nền gần trắng (`--canvas`) cho vùng nội dung, sidebar
   và header — ngăn bằng đường kẻ mảnh; thẻ trắng (`--card`); viền mảnh (`--border`) tạo cấu trúc, không dùng bóng đổ
   để chia khối; thứ gõ/bấm được (ô nhập, ô chọn, nút viền, chip) viền `--input` đậm hơn. Chữ hai mức: gần đen
   (`--foreground`) và phụ (`--muted-foreground`, ≥ 7:1). Không quay lại nền giấy be + chữ nâu của groq.com: người
   dùng thấy "khó nhìn" (10/11/2026).
2. **Một màu nhấn: cam Groq** (`--primary` nền đặc, `--brand` chữ/icon/dải, `--ring` focus). **Không dùng xanh dương
   làm màu chủ đạo** (người dùng đã từ chối). Màu nhấn chỉ cho: nút chính, thứ đang được chọn (mục sidebar, thẻ, chip
   lọc, đường đi trong đồ thị), vòng focus, kết luận chính của trang (dải trái + nhãn của tóm tắt AI), logo, ô icon
   tiêu đề trang, trạng thái "đang chạy". Tối đa khoảng 3–5 chỗ mỗi màn hình.
3. **Màu ngữ nghĩa chỉ khi có nghĩa**, và phải khác hẳn màu cam: ô-liu `--success` (thành công, đã xác nhận, nguyên
   nhân gốc, bản sửa), **mù tạt** `--warning` (cần để ý — chờ quyết định, thiếu dữ liệu, chưa lưu, bị tắt), **đỏ thẫm**
   `--destructive` (lỗi, triệu chứng, nguy hiểm, bị bác — giống Groq để lỗi không trông như thương hiệu). Thông tin thụ
   động: **trung tính, không tô màu**.
4. **Màu nằm trên dấu nhỏ, không trên cả khối:** icon, thanh màu của nút đồ thị, badge, dải trái. Không tô nền cả thẻ
   theo loại (ba thẻ "triệu chứng" tô đỏ liền nhau đọc thành báo động chứ không phải xếp hạng). Ngoại lệ có chủ đích:
   nền nhạt cho thứ cần người xử lý (thẻ chờ duyệt, nguyên nhân gốc, ô bản sửa, thông báo lỗi/thành công).
5. **Dải trái** (`border-l-4`) cho khối cần để ý: chờ duyệt = mù tạt, nguy hiểm/thất bại = đỏ thẫm, nguyên nhân gốc =
   ô-liu, kết luận chính (tóm tắt AI) = cam. Khối bình thường không có dải.
6. **Badge 5 tone:** `neutral`, `accent` (**viền cam, nền trong** — như nút pill của Groq, để khác badge trạng thái cả
   về hình), `success`, `warning`, `danger` (nền nhạt + chữ đậm màu). Phân loại không mang nghĩa (vai trò
   engineer/user, nguồn skill, loại "state") dùng `neutral`.
7. **Nhãn kiểu Groq** (`eyebrow`: Space Grotesk, 12px, đậm 600, viết hoa, giãn chữ 0,06em — như nhãn nhóm của
   console; bản đầu dùng mono 11px, quá mờ) cho tiêu đề nhóm và nhãn phía trên khối ("AI SUMMARY", "NEXT STEPS",
   "PROPOSED CHANGE"). Không dùng cho câu văn. Tiêu đề `h1`–`h3` tự nhận Space Grotesk; chữ thường là Inter.
8. **Màu không đứng một mình:** luôn kèm chữ hoặc icon (người mù màu đỏ–lục).
9. **Tương phản:** tối thiểu WCAG là chữ ≥ 4,5:1, viền/icon ≥ 3:1, nhưng ở đây cố ý cao hơn nhiều: chữ chính ≥ 16:1,
   chữ phụ ≥ 6,9:1 trên thẻ và nền, ở cả sáng và tối (cam của Groq `#f43e01` chỉ dùng cho vòng focus; chữ cam dùng `#c23101`, nút cam
   `#d63601`).
10. **Chỉ dùng token** trong `globals.css`; không viết `emerald-*`, `amber-*`, `sky-*`, `violet-*`… trực tiếp
    (ngoại lệ: bộ màu phân loại của avatar).

## 3. Token

| Token | Sáng | Tối | Dùng cho |
|---|---|---|---|
| `--canvas` | `#fafaf9` (stone-50) | `#0c0a09` | nền nội dung, sidebar, header |
| `--card` / `--background` | `#ffffff` | `#1c1917` | thẻ; ô nhập, nút viền, popover |
| `--foreground` | `#0c0a09` (chữ console, ~19:1) | `#fafaf9` | chữ chính |
| `--muted-foreground` | `#57534e` (stone-600, 7,6:1) | `#a8a29e` (6,9:1) | chữ phụ |
| `--muted` / `--accent` | `#f5f5f4` / `#efeeec` | `#292524` | nền nhạt; nền hover/đang chọn |
| `--border` / `--input` | `#e7e5e4` / `#d6d3d1` | trắng 12% / 22% | đường kẻ mảnh / viền ô nhập, ô chọn, nút viền, chip |
| `--primary` / `-foreground` | `#d63601` / trắng (4,8:1) | `#f43e01` / gần đen (5,2:1) | nút chính, chip/switch bật, logo |
| `--brand` | `#c23101` (5,6:1) | `#ff7a45` | chữ, icon, dải, đường đi đồ thị |
| `--ring` | `#f43e01` | `#ff7a45` | vòng focus |
| `--success` | `#475c05` (ô-liu Groq) | `#9ccc4c` | thành công |
| `--warning` | `#8a5c00` (mù tạt) | `#f6ab45` (vàng Groq) | cần để ý |
| `--destructive` | `#c7083a` (đỏ thẫm) | `#ff5c7c` | lỗi, nguy hiểm |

Đổi màu nhấn sau này: chỉ sửa `--primary`, `--brand`, `--ring` (hai chế độ) — mọi trang đổi theo.

## Kiểm tra

- Typecheck + lint frontend; xem từng trang trong trình duyệt (sáng; tối bằng class `.dark`).
- Không còn lớp màu cứng ngoài avatar (`grep -E "(emerald|amber|sky|violet)-[0-9]"`).
