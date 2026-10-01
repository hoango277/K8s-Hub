# K8s Hub

Nền tảng vận hành Kubernetes có AI hỗ trợ. Backend FastAPI + LangGraph, frontend
Next.js. Xem `README.md` để biết kiến trúc dự kiến, nhưng nhớ rằng README mô tả
**kế hoạch** — phần lớn kho mã hiện vẫn là file khung chỉ có docstring kèm `TODO`.

## Quy tắc thường trực: cập nhật báo cáo hiện trạng

**Mỗi khi thay đổi mã nguồn, cập nhật luôn `docs/hien-trang-codebase.md` cho khớp.**

Không đợi được nhắc. Áp dụng cho: viết module mới, vá lỗi, nối một tích hợp,
thêm hoặc bớt phụ thuộc, biến một file khung thành mã thật. Làm xong phần việc
chính thì cập nhật báo cáo ngay trong cùng lượt, rồi nói ngắn gọn đã sửa mục nào.

Vì sao quan trọng: kho này có rất nhiều file khung rỗng và README thì nói về kế
hoạch, nên `docs/hien-trang-codebase.md` là tài liệu duy nhất nói đúng những gì
thực sự chạy được. Một bản lạc hậu còn tệ hơn không có, vì người đọc sẽ tin nó.

Skill `cap-nhat-hien-trang` mô tả quy trình quét lại kho mã và bố cục bảy mục của
báo cáo. Dùng nó khi cập nhật.

## Môi trường phát triển

```bash
# Backend — Python nằm trong venv, KHÔNG phải `python` trên PATH
cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --reload
cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q
cd backend && .venv/Scripts/python.exe -m ruff check app/

# Frontend
cd frontend && npm run dev
cd frontend && npm run typecheck
```

Cài lại phụ thuộc: `pip install -r backend/requirements-dev.txt`. Máy không có
`uv` dù README có nhắc tới.

## Ba cái bẫy hay mất thời gian

- **`PYTHONUTF8=1` là bắt buộc.** Console Windows dùng cp1252, log tiếng Việt sẽ
  ném `UnicodeEncodeError` và che mất lỗi thật.
- **`git` báo "dubious ownership"** vì kho được tạo từ một tài khoản Windows khác.
  Dùng `find` thay `git ls-files`, hoặc `git -c safe.directory=D:/SCHOOL/K8s-Hub`.
- **Hạ tầng nằm trên cụm Kubernetes `lab1`**, không phải localhost và không dựng
  bằng Docker ở máy phát triển. `.env` trỏ Postgres tới `lab1:30432`. Kho không
  có `docker-compose.yml` — đừng gợi ý `docker compose up`.

## Quy chuẩn giao diện (UI/UX)

**Mọi trang phải đẹp và theo đúng các quy chuẩn dưới đây** — kể cả trang chưa có
tính năng. Đối chiếu danh sách này trước khi coi một trang là xong.

**Hệ thống thiết kế**
- Chỉ dùng token màu trong `src/app/globals.css` (`var(--primary)`,
  `var(--muted-foreground)`, `var(--destructive)`...). Không viết mã màu cứng —
  token là thứ giữ cho chế độ sáng/tối khớp nhau.
- Dùng lại component có sẵn trong `src/components/ui/` trước khi viết mới:
  `button`, `badge`, `page-header`, `empty-state`, `spinner`, `confirm-dialog`,
  `select`. Không tự viết lại chuỗi class cho nút — dùng `Button`.
- Khoảng cách theo thang 4px của Tailwind; bo góc `rounded-lg` cho khối,
  `rounded-md` cho nút/ô nhập. Nội dung trang giới hạn `max-w-*` và căn giữa,
  không trải hết màn hình rộng.
- Mỗi trang mở đầu bằng `PageHeader`: tiêu đề, một câu mô tả trang dùng để làm
  gì, và nút hành động chính (nếu có) ở góc phải.

**Đủ bốn trạng thái** cho mọi vùng hiển thị dữ liệu: đang tải (skeleton hoặc
spinner, không để trắng), lỗi (nói rõ chuyện gì và làm gì tiếp), trống (giải
thích và chỉ đường, không chỉ ghi "không có dữ liệu"), có dữ liệu. Trang chưa
làm tính năng dùng `EmptyState` mô tả trang sẽ làm gì — không được `return null`.

**Form**
- Mọi ô nhập có `<label>` gắn `htmlFor`; placeholder không thay được nhãn.
- Kiểm tra phía client những gì backend sẽ từ chối (độ dài, định dạng) và báo
  lỗi ngay dưới đúng ô đó; lỗi từ máy chủ hiện gần nút gửi.
- Nút gửi hiện trạng thái đang xử lý và bị khoá trong lúc chờ, để không gửi đôi.

**Thao tác**
- Hành động phá huỷ hoặc khó đảo ngược (xoá, khoá tài khoản, đổi quyền) phải
  qua `ConfirmDialog` với `destructive`. Không dùng `window.confirm()`/`alert()`.
- Không dùng `<select>` gốc của trình duyệt — dùng `ui/select.tsx` (Radix).
- Sau mỗi thao tác phải có phản hồi thấy được (thông báo, đổi trạng thái tại chỗ).
- Ẩn hẳn những gì vai trò hiện tại không được dùng, thay vì để người dùng bấm
  vào rồi nhận lỗi 403.

**Truy cập (a11y)**
- Làm được mọi việc bằng bàn phím; `focus-visible` phải thấy rõ.
- Nút chỉ có icon phải có `aria-label`; icon trang trí có `aria-hidden`.
- Vùng bấm tối thiểu ~32px; chữ đủ tương phản trên cả nền sáng lẫn tối.
- Mọi hiệu ứng chuyển động phải tắt khi bật `prefers-reduced-motion`.

**Giọng văn giao diện**: ngắn, nói điều người dùng cần làm. Thông báo lỗi không
lộ chi tiết kỹ thuật thừa.

## Ngôn ngữ: TOÀN BỘ bằng tiếng Anh

**Mọi thứ trong mã nguồn và mọi thứ người dùng nhìn thấy đều viết bằng tiếng Anh**
(áp dụng từ 25/09/2026):

- Giao diện: nhãn, nút, tiêu đề trang, thông báo, trạng thái trống, `aria-label`,
  `metadata.title`, định dạng ngày giờ (`date-fns` dùng locale mặc định `en-US`).
- Backend: `detail` của `HTTPException`, `message` của sự kiện lỗi SSE, thông báo
  của exception, mô tả trường (`Field(description=...)`) — những thứ này hiện ra
  trên giao diện — và cả log.
- Trợ lý AI: lời nhắc hệ thống, mô tả công cụ và kết quả công cụ bằng tiếng Anh.
  Riêng **câu trả lời** của trợ lý thì theo ngôn ngữ người dùng hỏi — hỏi tiếng
  Việt trả lời tiếng Việt, hỏi tiếng Anh trả lời tiếng Anh.
- Mã: comment, docstring, tên biến/hàm/lớp, tên test — ở cả backend, frontend và
  test. Không đặt tên kiểu `tro_ly`, `dangChay`; dùng `assistant`, `isStreaming`.

Còn giữ tiếng Việt: tài liệu viết cho người dùng (`CLAUDE.md` này,
`docs/hien-trang-codebase.md`, skill `cap-nhat-hien-trang`) và tên ràng buộc CSDL
đã nằm trong migration (ví dụ `role_hop_le`) — đổi chúng cần migration riêng.

## Tài khoản và phân quyền

Ba vai trò: `admin` (toàn quyền), `engineer` (sau này thêm/sửa/xoá skill, runbook),
`user` (hỏi đáp, chạy skill có sẵn — không thêm sửa xoá).

- **Admin có MỌI quyền.** Admin luôn qua mọi kiểm tra vai trò: `has_role` trong
  `app/api/deps.py` (backend) và `hasRole` trong `src/lib/roles.ts` (frontend,
  cho sidebar và `RoleGate`). Endpoint mới chỉ cần ghi vai trò thấp nhất được
  phép, ví dụ `require_role("engineer")`, không cần liệt kê thêm `"admin"`. Đừng
  so vai trò bằng `==`/`includes` trực tiếp — sẽ khoá mất admin.
- **Tài khoản chỉ KHOÁ, không XOÁ.** Không thêm `DELETE /users/{id}` hay nút xoá.
  Xoá sẽ kéo theo toàn bộ lịch sử hội thoại (ON DELETE CASCADE) và không đảo
  ngược được; khoá (`is_active=false`) thì mở lại được.
- Admin quản lý tài khoản: tạo, sửa tên, đổi vai trò, khoá/mở khoá, đặt lại mật
  khẩu. Hai thao tác bị chặn có chủ ý: tự hạ quyền/tự khoá chính mình, và làm
  mất admin đang hoạt động cuối cùng.
- Mọi vai trò tự sửa được tên hiển thị (`PATCH /auth/me`, trang My account) và tự
  đổi mật khẩu. Schema tự sửa chỉ nhận `display_name` (`extra="forbid"`) để không
  ai tự nâng quyền qua đó.
- Quyền thật luôn chặn ở backend; frontend chỉ ẩn những gì vai trò hiện tại không
  dùng được.

## Skill và Tool: hai tầng khác nhau

- **Skill = chuẩn Agent Skills**: mỗi skill là một thư mục chứa `SKILL.md` (YAML
  front matter có ít nhất `name`, `description`; phần dưới là hướng dẫn) cùng các
  thư mục tuỳ chọn `scripts/`, `references/`, `assets/`. Code ở
  `app/modules/skills/`. **Skill KHÔNG phải công cụ LangChain** — đừng gọi công cụ
  là "skill" trong mã hay giao diện.
- **Tool = code LLM gọi được**: đọc pod/mọi loại tài nguyên, metrics, log, trace,
  đề xuất thay đổi, và custom tool. Code ở `app/modules/tools/`. Skill hướng dẫn
  agent dùng tool nào.
- Nạp skill theo **progressive disclosure**: chỉ `name` + `description` vào system
  prompt; thân SKILL.md qua `load_skill`, file phụ qua `read_skill_file`, script
  qua `run_skill_script`.
- Skill mẫu nằm trong repo (`backend/skills/<name>/`, chỉ đọc trên web); skill tạo
  hoặc import trên web lưu CSDL, có Import/Export `.zip` đúng chuẩn.
- **MCP server bên ngoài: chỉ admin/engineer thêm, và họ chọn từng tool có cần
  phê duyệt hay không** (bỏ ngày 30/09, thêm lại 01/10/2026 theo yêu cầu người
  dùng). Tool mới **tắt + cần phê duyệt**, mặc kệ server tự nhận `readOnlyHint`.
  Tool cần phê duyệt thì lời gọi thành đề xuất trong bảng `approvals` (không có
  dry-run, thẻ hiện đúng tham số); tool được bỏ phê duyệt thì gọi thẳng. Chính
  sách đọc lúc gọi nên đổi là có hiệu lực ngay. Tắt phê duyệt phải qua
  `ConfirmDialog` destructive. Token server mã hoá, không lưu trong `plan`.
- **Custom tool theo kiểu kubectl-ai**: engineer khai báo trên web một CLI
  (`command` cố định, mô tả, cách dùng, danh sách **lệnh con chỉ đọc**). LLM chỉ
  viết phần đối số; chạy không qua shell. Lệnh khớp tiền tố chỉ đọc chạy ngay
  trong sandbox, còn lại thành đề xuất chờ duyệt. Luôn chặn Secret, `-w/--watch`,
  `logs -f`, `exec -it`, `port-forward`.
- **Script và lệnh chạy trong sandbox** (`SANDBOX_BACKEND`): `local` = tiến trình
  con trên backend (hàng rào, không cô lập); `kubernetes` = pod sandbox
  (`deploy/sandbox/sandbox.yaml`) — container `runner` không có token chạy script,
  container `cli` có ServiceAccount riêng (không đọc Secret) chạy lệnh. Ai sửa
  được skill/custom tool là chạy được mã ở đó, nên chỉ engineer+ tạo/sửa.
- Tool đọc cụm: LLM không viết PromQL/LogQL/TraceQL, kết quả luôn được tóm tắt,
  Secret không bao giờ được đọc.

## Thay đổi cụm: luôn qua phê duyệt

- Tool ghi (`scale_workload`, `restart_workload`, `set_image`, `delete_pod`, `delete_resource`,
  `apply_manifest`, lệnh ghi của custom tool, tool MCP đang "cần phê duyệt") **chỉ ĐỀ XUẤT**: dựng kế hoạch →
  kiểm tra (namespace được phép, namespace bảo vệ như `kube-system`, đối tượng
  tồn tại) → **dry-run phía server** + diff → lưu vào bảng `approvals`. Không có
  đường nào để LLM tự thay đổi cụm.
- Lượt chat **không treo** chờ người duyệt: đề xuất được lưu, lượt kết thúc;
  engineer/admin quyết định sau (thẻ trong chat hoặc trang Approvals). Kết quả
  được ghi lại vào hội thoại thành ghi chú hệ thống để lượt sau trợ lý biết.
- Thứ được chạy là **đúng `plan` đã lưu** lúc dry-run, không hỏi lại LLM. Đề
  xuất hết hạn sau `APPROVAL_TTL_MINUTES`. Sau khi chạy có bước kiểm tra lại
  (rollout xong chưa…). Dòng `approvals` không bao giờ xoá — nó là nhật ký.
- `K8S_EXECUTION_MODE`: `read_only` không đưa tool ghi cho LLM; `auto` chỉ bỏ
  qua phê duyệt khi người yêu cầu là engineer/admin.

## Giám sát: mỗi thứ đúng một chỗ

- **Langfuse = mọi thứ về con AI**: token, chi phí, lời gọi công cụ, độ trễ từng
  bước, theo người dùng/hội thoại. **Không chép sang Prometheus** — hai nguồn sẽ
  lệch nhau.
- **Prometheus (`/metrics`, `core/telemetry.py`) = chỉ sức khoẻ dịch vụ**: số
  request, lỗi, độ trễ, luồng SSE đang mở. Label ít giá trị, không bao giờ gắn
  theo người dùng/hội thoại/trace.
- **Trace của ứng dụng trên cụm = Tempo** (`TEMPO_URL`, đọc qua
  `integrations/tempo/client.py`), khác Langfuse (trace của chính con AI). LLM
  không bao giờ nhận TraceQL thô hay trace JSON thô: truy vấn dựng từ tham số đã
  kiểm, trace được tóm tắt trước (`summarize_trace`).
- **Log chỉ ra stdout** (`LOG_FORMAT=text|json`). App **không tự đẩy log lên
  Loki**: trên cụm, Alloy đã gom stdout của mọi pod.
- Không cấu hình cho Prometheus scrape máy dev. Khi backend chạy thành pod thì
  thêm ServiceMonitor cùng Deployment.

## Quy ước viết mã

Comment và docstring giải thích **vì sao** chứ không chỉ **làm gì** — kho này đã
theo lối đó khá nhất quán, nhất là ở những chỗ từng vấp lỗi. Giữ nguyên tinh
thần đó khi viết bằng tiếng Anh.

`app/schemas/events.py` và `frontend/src/types/events.ts` là một hợp đồng: sửa
một bên thì phải sửa bên kia, đã có test kiểm điều này.
