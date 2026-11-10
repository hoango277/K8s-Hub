# Kế hoạch: hoàn tác thay đổi đã chạy (Revert)

*Ngày 10/11/2026. Người dùng đồng ý gợi ý "hoàn tác thay đổi đã chạy: tạo đề xuất ngược lại (scale về số cũ, image cũ)
và vẫn qua phê duyệt; cần lưu thêm trạng thái trước khi chạy". Đây là **kế hoạch**; trạng thái chạy thật ghi ở
`docs/hien-trang-codebase.md`.*

## Tiến độ

| Hạng mục | Trạng thái |
|---|---|
| 1. Lưu trạng thái trước khi chạy (`approvals.before_state`) + phiên bản ngay sau khi chạy | **Xong** (10/11/2026) — migration `7e2a9c4d1b60` đã áp vào CSDL dev |
| 2. Dựng kế hoạch ngược theo từng loại thay đổi (`nl_command/revert.py`) | **Xong** |
| 3. API `POST /approvals/{id}/revert`, liên kết `reverts_id`, trường `revertible`/`revert_blocker`/`revert` | **Xong** |
| 4. Giao diện: nút Revert trên thẻ đã chạy, thẻ đề xuất hoàn tác, lý do khi không hoàn tác được | **Xong** |
| 5. Test + kiểm trên trình duyệt | **Xong** — 22 test đơn vị; Chrome (API giả lập + dữ liệu thật); **chạy thật trên lab1** (người dùng đồng ý, 10/11/2026): 6 bước trong `rca-lab` — tạo, scale + hoàn tác, sửa + hoàn tác (PUT), hoàn tác bước tạo (xoá) — đều executed + kiểm tra lại đạt, namespace trống lại |

## Nguyên tắc

- Hoàn tác **không phải nút "undo" chạy ngay**: nó tạo một **đề xuất mới** theo chiều ngược, đi đúng đường cũ —
  kiểm tra (namespace bảo vệ, đối tượng tồn tại) → dry-run phía server → diff → chờ engineer/admin duyệt → chạy →
  kiểm tra lại. Thứ được chạy vẫn là `plan` đã lưu lúc dry-run.
- **Không bao giờ tự chạy**, kể cả chế độ `auto`: đề xuất hoàn tác dùng vai trò `user`, như bản sửa từ RCA — kế hoạch
  do hệ thống tự dựng, phải có người đọc diff.
- Dòng gốc giữ nguyên (bảng `approvals` là nhật ký); dòng hoàn tác trỏ về gốc bằng `reverts_id`, ghi chú kết quả vào
  đúng hội thoại của thay đổi gốc. Hoàn tác của một hoàn tác (làm lại) dùng cùng cơ chế.
- Mỗi thay đổi chỉ có một hoàn tác đang chờ/đang chạy tại một thời điểm.

## 1. Trạng thái trước khi chạy

- Chụp **lúc chạy**, không phải lúc đề xuất: duyệt có thể đến sau 60 phút, cụm đã khác.
- Ngay trước khi chạy: GET từng đối tượng trong `plan.ops` (đúng đường đọc của dry-run) → `approvals.before_state`
  (JSONB): `existed`, bản đối tượng đã làm sạch (bỏ `status`, `uid`, `resourceVersion`, `managedFields`,
  `creationTimestamp`, `generation`, annotation `deployment.kubernetes.io/revision`). Ngay sau khi chạy: ghi
  `resourceVersion`/`generation` mới để sau này biết đối tượng có bị đổi tiếp không.
- **Không bao giờ chứa Secret**: kế hoạch nào đụng Secret đã bị `resolve_kind` từ chối từ lúc dựng.
- Đối tượng > 256 KB không lưu (ghi `too_large`) → không hoàn tác được phần đó. Chụp lỗi thì vẫn chạy thay đổi
  (đã được duyệt), chỉ mất khả năng hoàn tác — có log cảnh báo.

## 2. Kế hoạch ngược theo loại

| Thay đổi gốc | Hoàn tác | Cách |
|---|---|---|
| `scale` | scale về số replica trước | `plan_scale(…, số cũ)` — giữ ghi chú HPA |
| `set_image` | đổi lại image cũ của đúng container | `plan_set_image(…, image cũ)` |
| `apply` — đối tượng mới tạo | xoá đối tượng | `DELETE`; Namespace = "dangerous" + ghi chú xoá mọi thứ bên trong |
| `apply` — đối tượng đã có | khôi phục bản trước | `PUT` bản trước kèm `resourceVersion` hiện tại: ai sửa tiếp giữa lúc đề xuất và lúc duyệt thì lúc chạy nhận 409 thay vì ghi đè âm thầm |
| `delete` (khác Namespace) | tạo lại | server-side apply bản trước; bỏ `ownerReferences` (chủ cũ có thể không còn), Service bỏ `clusterIP` |
| `delete_pod` không có controller | tạo lại pod | như trên, bỏ `nodeName` để scheduler đặt lại |
| `delete_pod` có controller | — | controller đã tạo pod thay thế |
| `delete` Namespace | — | mọi thứ bên trong đã mất; tạo lại namespace rỗng không phải là hoàn tác |
| `restart` | — | pod đã được thay; không có trạng thái nào để quay lại |
| `command`, `mcp` | — | K8s-Hub không biết lệnh/tool ngoài đã đổi gì |
| chạy trước khi có tính năng | — | không có `before_state` |

- Đối tượng **đã bị đổi tiếp** sau thay đổi gốc (so `generation`, hoặc `resourceVersion` với loại không có
  generation): thêm ghi chú trên thẻ — khôi phục bản trước cũng xoá luôn những sửa đổi sau đó; diff cho thấy hết.
- Không còn gì để hoàn tác (số replica/image đã về như cũ, đối tượng đã bị xoá/đã có lại) → báo lý do, không tạo đề xuất.

## 3. API

- `POST /approvals/{id}/revert` — mọi vai trò đã đăng nhập (chỉ tạo đề xuất; duyệt vẫn cần engineer+, như đề xuất từ
  chat). 201 + đề xuất mới; 409 kèm lý do khi không hoàn tác được hoặc đã có hoàn tác đang chờ.
- `ApprovalOut` thêm: `reverts_id` (dòng này hoàn tác dòng nào), `revert` (hoàn tác mới nhất của dòng này: id, trạng
  thái), `revertible`, `revert_blocker` (lý do không hoàn tác được — tính nhanh, không gọi cụm).

## 4. Giao diện

- Thẻ đã chạy: nút **Revert** (viền, icon hoàn tác) nếu hoàn tác được; không thì một dòng xám nói lý do.
- Sau khi bấm: thông báo + trong chat, thẻ gốc hiện luôn thẻ đề xuất hoàn tác bên dưới (diff + Approve/Reject tại
  chỗ); trên trang Approvals, thẻ gốc hiện một dòng trạng thái (thẻ hoàn tác đã nằm trong danh sách, không lặp lại).
- Thẻ hoàn tác có nhãn "Proposed revert" thay cho "Proposed change".

## Kiểm tra

- Test đơn vị (không cần cụm): làm sạch bản chụp; kế hoạch ngược cho scale, set_image, apply (tạo mới / đã có / đã bị
  đổi tiếp), delete (tạo lại, bỏ ownerReferences/clusterIP), delete_pod; các trường hợp bị chặn; chặn hoàn tác trùng;
  hoàn tác luôn chờ duyệt kể cả `auto`.
- Không chạy thật trên lab1 khi chưa được người dùng đồng ý (tạo dòng `approvals` và ghi vào cụm).
