# Hiện trạng codebase K8s Hub

*Báo cáo đọc mã, cập nhật ngày 25/09/2026 (lần 7). Mô tả những gì ĐANG CÓ trong kho, không phải kế hoạch.*

---

## 1. Tóm tắt trong một trang

K8s Hub được thiết kế quanh 4 use case: ra lệnh Kubernetes bằng ngôn ngữ tự nhiên, phân tích
nguyên nhân gốc (RCA), thư viện skill/runbook, và giám sát chính con AI. Kho mã đã dựng **đầy đủ
bộ khung thư mục cho cả 4**, nhưng mới **một use case chạy thật**.

| Mảng | Tình trạng |
|---|---|
| Khung trò chuyện có streaming + gọi công cụ | **Chạy được đầu-cuối**, có test |
| Tầng cấu hình (đa nhà cung cấp LLM, đổi nóng) | **Chạy được**, có test, khá hoàn chỉnh |
| Lưu hội thoại vào PostgreSQL + migration | **Chạy được** |
| Trang Cấu hình trên web | **Chạy được** — lưu xuống Postgres, có lịch sử thay đổi và trạng thái kết nối |
| Kết nối Kubernetes | Chưa có dòng mã nào |
| Đọc trace ứng dụng trên cụm (Grafana Tempo) | **Chạy được đầu-cuối**: 3 công cụ cho trợ lý, đã thử với Tempo thật trên lab1 |
| RCA | Chỉ có khung file |
| Skills / MCP / runbook | Chỉ có khung file |
| Tracing: OTel + Langfuse | **Chạy thật** với Langfuse trên `lab1:30400`, đã kiểm trace đầu-cuối |
| Audit log, đo lường chất lượng | Chỉ có khung file |
| Đăng nhập, phân quyền (JWT, 3 vai trò) | **Chạy được đầu-cuối** (backend + frontend), đã kiểm qua HTTP thật |
| Quản trị người dùng (trang `/users`) | **Chạy được**, đã kiểm bằng trình duyệt thật |

Về khối lượng: backend có ~5.300 dòng Python, nhưng **57 file chỉ chứa một dòng docstring
kèm `TODO`** (không tính `__init__.py`). Frontend có 26 component/hook/type ở dạng khung rỗng — nhưng
không còn **trang** nào trắng: trang chưa có tính năng hiện mô tả những gì nó sẽ làm. Nghĩa là cấu
trúc dự án đã được nghĩ xong và đóng cọc sẵn; phần thịt mới đắp vào một nhánh.

Điểm mạnh rõ rệt của kho mã này là **chất lượng phần đã làm**: gần như mọi file đã hoàn thiện đều
có docstring giải thích *vì sao* làm như vậy, kể cả những cái bẫy đã vấp phải (streaming bị `rewrites`
của Next.js gom lại, `useSyncExternalStore` với `subscribe` rỗng, pgbouncer không dùng được prepared
statement). Đó là tài liệu có giá trị hơn hầu hết README.

**Toàn bộ mã nguồn và giao diện nay bằng tiếng Anh** (từ lần cập nhật 7): chữ trên giao diện, thông
báo lỗi của API và SSE, mô tả trường ở trang Cấu hình, lời nhắc hệ thống của trợ lý (trợ lý được dặn
trả lời theo ngôn ngữ người hỏi — tiếng Việt hoặc tiếng Anh), log, comment, docstring, tên biến/hàm và tên test. Quy tắc ghi ở mục "Ngôn ngữ"
của `CLAUDE.md`. Chỉ tài liệu viết cho người dùng (báo cáo này, `CLAUDE.md`) và tên ràng buộc CSDL đã
nằm trong migration (`role_hop_le`, `status_hop_le`, `ix_chat_threads_user_moi_nhat`) còn tiếng Việt.

---

## 2. Bản đồ kho mã

```
K8s-Hub/
├── backend/          FastAPI + LangGraph + SQLAlchemy async
│   ├── app/api/v1/   10 router: chat, auth, users, settings, health (thật) + 5 router rỗng
│   ├── app/core/     config.py (trung tâm hệ thống), security.py (JWT, bcrypt) + 3 file khung
│   ├── app/db/       models users/refresh_tokens/chat_threads/messages/tool_calls + session
│   ├── app/integrations/  llm/ (xong) · k8s, prometheus, loki (khung)
│   ├── app/modules/  nl_command (một phần) · observability (tracing xong) · rca, skills (khung)
│   ├── app/schemas/  events.py, chat.py, auth.py (xong) + 5 file khung
│   ├── app/services/ thread, auth, user service (xong) + 2 file khung
│   ├── migrations/   4 revision Alembic
│   └── tests/unit/   12 file test (170 test, đều xanh)
├── frontend/         Next.js 16 + React 19 + Tailwind v4 + TanStack Query
│   └── src/          đăng nhập, chat, người dùng, cấu hình làm thật; 4 trang còn lại là "sắp có"
│       └── components/ui/  bộ component nền theo quy chuẩn UI/UX trong CLAUDE.md
├── deploy/helm/      thư mục rỗng — chưa có manifest triển khai
├── .claude/skills/   cap-nhat-hien-trang — quy trình cập nhật chính tài liệu này
└── docs/             3 file kế hoạch .xlsx + báo cáo này
```

---

## 3. Những gì đã chạy được

### 3.1 Luồng trò chuyện có streaming — xương sống của hệ thống

Đây là phần được đầu tư nhiều nhất và là thứ duy nhất chạy hết một vòng từ trình duyệt xuống
mô hình rồi quay lại cơ sở dữ liệu.

Đường đi của một câu hỏi:

```
Trình duyệt (fetch + POST)
  → Next.js route handler  frontend/src/app/api/backend/[...path]/route.ts
  → FastAPI                backend/app/api/v1/chat.py  POST /chat/threads/{id}/stream
  → LangGraph              app/modules/nl_command/agent.py
  → mô hình + công cụ      app/integrations/llm/client.py, nl_command/tools.py
  → dịch sự kiện           app/integrations/llm/streaming.py
  → khung SSE              app/schemas/events.py
  → về lại trình duyệt     frontend/src/lib/sse.ts → hooks/use-chat-stream.ts
```

Những quyết định kỹ thuật đáng ghi nhận trong luồng này:

- **Không dùng `rewrites` của Next.js để proxy.** File `route.ts` ghi lại con số đo được: 25 sự kiện
  của một lượt chat về cùng lúc ở giây 12,7 thay vì rải đều trong 4 giây. Route handler trả thẳng
  `upstream.body` nên dữ liệu chảy tới đâu ra tới đó.
- **Chuẩn bị xong rồi mới mở luồng.** `chat.py` kiểm tra hội thoại, kiểm tra nhà cung cấp, ghi câu
  hỏi và `commit` trước khi trả `EventSourceResponse`. Luồng đã mở thì không đổi được mã HTTP nữa,
  nên lỗi phát hiện muộn sẽ thành "200 kèm một sự kiện lỗi" thay vì 404 rõ ràng.
- **Phiên CSDL riêng cho phần chạy trong luồng.** Phiên của request giữ một kết nối trong bộ gộp
  cho tới khi response kết thúc — mà response ở đây kéo dài hàng phút.
- **Đóng tab giữa chừng vẫn lưu được phần đã nói.** Không chỉ nhờ khối `finally`: `sse-starlette`
  huỷ luôn task đang chạy generator, nên lệnh ghi phải nằm trong một `asyncio.Task` riêng bọc
  `asyncio.shield` mới sống sót. Chạy trọn vẹn thì vẫn chờ ghi xong trước khi phát `done`, để client
  nạp lại đọc được bản đã chốt.
- **Tách riêng phần suy luận (thinking) khỏi câu trả lời.** `_reasoning_of()` xử lý hai dạng khác
  nhau: `reasoning_content` của Groq và cờ `thought=True` của Gemini.
  Trộn hai thứ vào nhau là nguy hiểm vì suy luận chứa cả kết luận sai mà mô hình tự bác bỏ.
- **Hợp đồng sự kiện SSE được kiểm bằng test.** `tests/unit/test_events_contract.py` đọc thẳng
  `frontend/src/types/events.ts` và so với `app/schemas/events.py`, nên sửa một bên mà quên bên kia
  thì test đỏ.

Schema sự kiện đã định nghĩa sẵn 12 loại: `token`, `thinking`, `step`, `tool_call_start/end`,
`plan`, `approval_required`, `approval_resolved`, `verify_result`, `error`, `done`, `heartbeat`.
Mới 6 loại đầu được phát ra thật; nhóm `plan`/`approval_*`/`verify_result` là hợp đồng dành sẵn cho
pipeline duyệt thao tác chưa làm.

### 3.2 Tầng cấu hình — phần được thiết kế kỹ nhất

`backend/app/core/config.py` là file quan trọng nhất trong kho. Nó làm bốn việc:

1. **Hai tầng cấu hình chồng lên nhau**: `.env` (cứng, đọc một lần lúc khởi động) + phần người dùng
   đổi trên web (nóng). Kết quả là `settings` — một proxy luôn hỏi lại giá trị mới nhất, nên module
   nào `from app.core.config import settings` cũng không bị cầm object cũ.
2. **Danh sách trắng những gì đổi được lúc chạy**: tổng cộng 11 trường, trong đó
   `RUNTIME_EDITABLE_SECRETS` giữ 2 khoá API của các nhà cung cấp LLM (ghi vào được nhưng không bao
   giờ đọc ra). `DATABASE_URL`, `JWT_SECRET` và cả nhóm `LANGFUSE_*` cố tình không nằm trong đó —
   xem mục 3.7 để biết vì sao Langfuse phải là cấu hình khởi động.
3. **Kiểm tra trước khi áp**: sai một trường thì cả lô bị từ chối và cấu hình đang chạy giữ nguyên.
4. **Cơ chế `on_reload()`**: module nào có bộ nhớ đệm dựng từ cấu hình thì đăng ký hàm dọn đệm.
   Hiện có 4 nơi dùng: bộ đệm model LLM, engine CSDL, danh mục model, tài khoản cục bộ. Engine CSDL
   chỉ dựng lại khi `DATABASE_URL` thật sự đổi — trước đây mỗi lần lưu bất kỳ trường nào (kể cả
   temperature) đều vứt pool kết nối và trả lại 0,6–1 giây đi-về tới lab1 ở truy vấn kế tiếp.
5. **Lưu bền xuống Postgres** (`services/settings_service.py`). `config.py` vẫn đồng bộ và giữ cấu
   hình đang chạy trong bộ nhớ; endpoint Settings (async) áp thay đổi rồi ghi bảng
   `settings_overrides` + một dòng `settings_changes` cho mỗi trường đổi. Ghi CSDL lỗi thì **trả bộ
   nhớ về như cũ** và báo 503 — trang không bao giờ hiện một thay đổi mà restart sẽ làm mất. Lúc
   khởi động, `lifespan` nạp lại qua `load_persisted_overrides()`. Khoá API lưu **mã hoá** (Fernet,
   khoá dẫn xuất từ `JWT_SECRET`): bản dump CSDL không còn lộ khoá dùng được; đổi `JWT_SECRET` thì
   khoá đã lưu bị bỏ qua kèm cảnh báo, phải nhập lại. Lịch sử không bao giờ chứa giá trị khoá.
   Đã kiểm thật: đổi `LLM_MAX_RETRIES`, khởi động lại backend, giá trị vẫn còn.

Hệ thống chỉ hỗ trợ **hai nhà cung cấp: Groq và Google (Gemini)**. Anthropic đã được gỡ hẳn — đặc tả,
khoá API, bộ đọc danh sách model và gói `langchain-anthropic`.

Đặc tả nhà cung cấp LLM (`ProviderConfig`) là chỗ hấp thụ khác biệt giữa Groq và Google: `param_map`
ánh xạ tên tham số chuẩn sang tên thật (Gemini gọi `max_tokens` là `max_output_tokens` và `api_key`
là `google_api_key`, Groq gọi `timeout` là `request_timeout`). Danh mục này là **mã**
(`DEFAULT_LLM_PROVIDERS`), không còn ghi đè được qua `.env` — thêm nhà cung cấp mới thì thêm một mục
ở đó.

**Nhà cung cấp và model không còn là cấu hình.** Bốn biến `LLM_PROVIDER`, `LLM_MODEL`,
`LLM_FAST_MODEL`, `LLM_PROVIDERS` đã bỏ khỏi `.env` và trang Cấu hình: người dùng chọn cho từng lượt
chat ở ô chọn model, danh sách lấy thẳng từ API nhà cung cấp, nên giữ thêm một nơi đặt "model đang
dùng" chỉ tạo ra hai câu trả lời khác nhau cho cùng một câu hỏi. Khi người dùng chưa chọn gì, nhà cung
cấp mặc định là **cái đầu tiên đã điền khoá API** (`Settings.llm_default_provider()`, thứ tự groq →
google) với model mặc định trong đặc tả — đúng quy tắc frontend (`use-models.ts`) đang
dùng, nên hai phía luôn khớp. Trước đây `LLM_PROVIDER` có thể trỏ vào một nhà cung cấp chưa có khoá
và hệ thống vỡ ngay câu chat đầu tiên; giờ trường hợp đó không xảy ra được nữa. Biến cũ còn sót trong
`.env` bị bỏ qua, không gây lỗi.

`catalog.py` đi thêm một bước: hỏi thẳng API của nhà cung cấp để lấy danh sách model, thay vì viết
cứng một danh sách sẽ sai trong vài tháng. Phần lọc model không-phải-chat (`whisper`, `orpheus`,
`llama-prompt-guard`) dựa trên trường dữ liệu trả về chứ không dựa vào tên model.

### 3.3 Lưu trữ

Các bảng đã có model và migration:

| Bảng | Vai trò |
|---|---|
| `users` | Chủ sở hữu hội thoại. Có `password_hash` (nullable — tài khoản OAuth-only sau này sẽ không có), `role`, `last_login_at` |
| `refresh_tokens` | Phiên đăng nhập có thể thu hồi — xem mục 3.8 |
| `chat_threads` | Một hội thoại. `last_message_at` tách khỏi `updated_at` để sửa tiêu đề không làm hội thoại nhảy lên đầu |
| `messages` | Có `reasoning`, `trace_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms` |
| `tool_calls` | Bảng riêng chứ không nhét JSON vào `messages`, để thống kê "công cụ nào hay lỗi nhất" chỉ cần một câu truy vấn |
| `settings_overrides` | Giá trị đổi trên trang Cấu hình (JSONB; khoá API lưu dạng `{"enc": ...}`), `updated_by` |
| `settings_changes` | Lịch sử chỉ-ghi-thêm: ai, lúc nào, trường nào, từ gì sang gì (khoá API chỉ ghi "đã đổi") |

Mọi quan hệ đặt `lazy="raise"` — đọc quan hệ chưa nạp sẵn sẽ báo lỗi ngay thay vì lặng lẽ bắn thêm
truy vấn giữa luồng bất đồng bộ. Quy ước đặt tên ràng buộc cố định trong `db/base.py` để Alembic
sinh tên ổn định.

`db/session.py` xử lý sẵn các bẫy của Supabase/pgbouncer: tắt prepared statement khi đi qua bộ gộp,
bắt buộc SSL với máy chủ ngoài, bỏ `pool_pre_ping` khi độ trễ cao, `pool_size=5`.

### 3.4 Giao diện

Chạy thật: **Đăng nhập/Đăng ký**, **Trò chuyện**, **Tài khoản** (đổi mật khẩu), **Người dùng**
(chỉ admin) và **Cấu hình** (chỉ admin).

Giao diện theo bộ quy chuẩn UI/UX ghi trong `CLAUDE.md` (mục "Quy chuẩn giao diện"): token màu dùng
chung, đủ bốn trạng thái tải/lỗi/trống/có dữ liệu, thao tác phá huỷ qua hộp xác nhận, hỗ trợ bàn
phím và "giảm chuyển động". Bộ component nền ở `src/components/ui/`: `button`, `badge`, `input`
(kèm `PasswordInput`, `Field`), `page-header`, `empty-state`, `spinner`, `avatar`, `confirm-dialog`,
`select`. Đã kiểm bằng cách chụp màn hình Chrome thật qua Playwright ở cả 1440px và 390px.

Giao diện bằng tiếng Anh, `<html lang="en">`, ngày giờ theo locale mặc định en-US của `date-fns`
(dạng `MMM d, yyyy`). Hook lưu localStorage nay là `hooks/use-local-storage.ts` (`useLocalStorage`);
prop nguy hiểm của `ConfirmDialog` là `destructive`.

- `chat-panel.tsx` — danh sách hội thoại, tạo/xoá, chọn model, khung chat streaming, nhớ hội thoại
  đang mở qua localStorage.
- `message-item.tsx`, `thinking-block.tsx`, `tool-call-card.tsx`, `markdown.tsx` — hiển thị câu trả
  lời, khối suy luận có đếm thời gian, thẻ gọi công cụ kèm tham số và kết quả.
- `model-picker.tsx` + `use-models.ts` — chọn nhà cung cấp và model cho riêng một lượt chat; lựa
  chọn được gửi kèm request và công cụ `system_info` đọc lại từ metadata để trợ lý khai đúng về
  chính nó.
- `settings/settings-page.tsx` — trang Cấu hình kiểu trang cài đặt thật: mục lục bên trái (trên
  điện thoại thành hàng tab cuộn ngang), mục đang mở nằm trong URL hash (`#keys`, `#history`…) nên
  tải lại/chia sẻ link/nút Back đều đúng. Bảy mục: **AI model**, **API keys**, **Cluster access**,
  **Connections**, **Change history**, **Advanced** (+ "Other" tự hiện nếu backend có trường mới
  chưa khai nhãn). `meta.ts` đổi tên biến `.env` thành nhãn dễ đọc kèm đơn vị; tên biến chỉ còn là
  chữ nhỏ bên dưới. Ô nhập đúng kiểu (`controls.tsx`): temperature là thanh trượt + ô số, chế độ
  thực thi là ba thẻ chọn có mô tả (Automatic có cảnh báo đỏ), namespace nhập dạng chip có kiểm
  tra tên DNS-1123. Kiểm tra giới hạn ngay dưới ô trước khi gửi. Thanh lưu chỉ hiện khi có thay đổi
  chưa lưu (đếm số thay đổi, chấm vàng trên mục chứa nó), rời/tải lại trang lúc chưa lưu thì trình
  duyệt hỏi lại. Mỗi trường có "Reset to default" hiện giá trị mặc định từ `.env`.
  `api-key-card.tsx`: trạng thái khoá (có/chưa, lấy từ `.env` hay đặt ở trang này), "Replace key",
  "Use .env key", và **Test** — gọi danh sách model của nhà cung cấp bằng khoá đã lưu ("The key
  works — 28 models available"). `connections-panel.tsx`: Database/Langfuse/Prometheus/Loki/Tempo có trả
  lời không, phiên bản, độ trễ, tự kiểm lại mỗi 30 giây. `history-panel.tsx`: "Changed Temperature
  from 0 to 0.4 — admin@… 5 minutes ago", tải thêm từng 20 dòng.
- `login-form.tsx` / `register-form.tsx` + `auth-shell.tsx` — trang xác thực hai cột, bên trái giới
  thiệu sản phẩm (ẩn trên màn hình hẹp). `auth-gate.tsx`, `role-gate.tsx`, `header.tsx` — xem mục 3.8.
- `users/user-admin.tsx` + `create-user-dialog.tsx` + `edit-user-dialog.tsx` +
  `reset-password-dialog.tsx` — trang quản trị người dùng: thẻ thống kê, tìm kiếm, lọc theo vai trò,
  đổi vai trò tại chỗ, sửa tên hiển thị (kể cả tên của chính admin), khoá/mở khoá, tạo tài khoản,
  đặt lại mật khẩu (có nút tạo mật khẩu ngẫu nhiên và sao chép). Đổi quyền và khoá đều phải qua hộp
  xác nhận. **Không có xoá tài khoản — có chủ ý**: chỉ khoá, vì xoá sẽ kéo theo toàn bộ lịch sử
  hội thoại (ON DELETE CASCADE) và không đảo ngược được.
- `account/account-page.tsx` — trang Tài khoản (bấm tên trên header để mở): hồ sơ, **tự sửa tên hiển
  thị** (mọi vai trò, qua `PATCH /auth/me` — schema chỉ nhận `display_name`, gửi kèm `role` bị 422)
  và form đổi mật khẩu với ô nhập lại, kiểm trước độ dài và khớp nhau ngay dưới từng ô.
- Khung chat khi trống hiện bốn câu hỏi gợi ý, bấm là gửi. Chỉ gợi ý những câu trợ lý trả lời được
  với công cụ hiện có — không gợi ý "pod nào đang lỗi?" khi chưa có công cụ tra cụm.

Thanh điều hướng chia hai nhóm "Vận hành" và "Quản trị"; nhóm Quản trị (Người dùng, Cấu hình) chỉ
`admin` thấy. Gõ thẳng URL thì `RoleGate` hiện trang "không có quyền" thay vì form sẽ lỗi 403.
Bốn trang Chẩn đoán, Kỹ năng, Chờ duyệt, Giám sát AI chưa có tính năng — hiện `ComingSoon` liệt kê
những gì trang sẽ làm, không còn trang trắng.

### 3.5 Công cụ trợ lý đang có

Năm công cụ, tất cả chỉ đọc:

- `system_info` — hệ thống đang chạy model nào, chế độ thực thi nào, namespace nào được phép, các
  nguồn dữ liệu (Prometheus, Loki, Tempo).
- `current_time` — thời điểm hiện tại UTC.
- `list_traced_services`, `search_traces`, `get_trace` — **trace của ứng dụng chạy trên cụm**, đọc từ
  Grafana Tempo (`TEMPO_URL`, lab1: `http://lab1:30200`). Không phải Langfuse: Langfuse là trace của
  chính con AI. `integrations/tempo/client.py` giữ hai nguyên tắc: (1) mô hình **không bao giờ gửi
  TraceQL thô** — `search_traces` nhận tham số rời (service, namespace, chỉ lỗi, ngưỡng thời gian,
  khoảng thời gian), mỗi giá trị được kiểm bằng biểu thức chặt trước khi ghép thành TraceQL;
  (2) mô hình **không bao giờ nhận trace JSON thô** (hàng trăm span tràn ngữ cảnh) —
  `summarize_trace()` rút gọn thành đường chậm nhất, các span lỗi (lỗi sâu nhất đứng đầu, vì lỗi
  ngoài thường chỉ là lan ra), và thời gian riêng của từng service. Khi `K8S_ALLOWED_NAMESPACES` có
  giá trị, tìm kiếm tự lọc theo danh sách đó và `get_trace` giấu các span ngoài danh sách. Để trống
  `TEMPO_URL` thì công cụ trả lời "chưa cấu hình nguồn trace" thay vì lỗi.

  Đã kiểm đầu-cuối: gửi một trace mẫu có đánh dấu (service `k8s-hub-selftest-*`, namespace
  `k8s-hub-selftest`) vào Tempo qua OTLP, rồi hỏi trợ lý bằng tiếng Việt "service … có request nào
  lỗi không, nguyên nhân gốc là gì" — trợ lý tự gọi `search_traces` rồi `get_trace` và chỉ ra đúng
  "payment timeout khi gọi DB → frontend trả 500". **Tempo hiện chưa có trace thật**: cần bật Beyla
  (component `beyla.ebpf` của Alloy) hoặc gắn OpenTelemetry cho app, và cho Alloy chuyển OTLP sang
  Tempo. `rca/collectors/traces.py` mới là khung, ghi rõ phải dùng lại client này.

`tools.py` ghi rõ ba ranh giới an toàn cho người thêm công cụ sau này: chỉ được đọc, không nhận chuỗi
lệnh thô (`run_kubectl(cmd)` bị cấm), và mô tả công cụ phải rõ vì đó là thứ mô hình đọc để quyết định.

### 3.6 Kiểm thử

12 file test đơn vị (170 test), không cần mạng và không cần CSDL:

| File | Kiểm gì |
|---|---|
| `test_chat_streaming.py` | Lớp dịch sự kiện LangGraph → SSE (chỗ dễ vỡ nhất khi nâng phiên bản) |
| `test_events_contract.py` | Backend và frontend khớp nhau |
| `test_llm_provider.py` | Ánh xạ tham số giữa các nhà cung cấp, chọn nhà cung cấp mặc định theo khoá API, đổi nóng cấu hình |
| `test_model_catalog.py` | Đọc danh sách model, dùng dữ liệu mẫu lấy từ phản hồi thật |
| `test_chat_tools.py` | Gọi công cụ thật (viết ra sau khi có lỗi lọt lưới) |
| `test_chat_history.py` | Đặt tiêu đề + nạp lịch sử làm ngữ cảnh |
| `test_auth_security.py` | Băm mật khẩu (bcrypt), JWT access/refresh, từ chối token sai loại |
| `test_user_guard.py` | Chặn admin tự hạ quyền/tự khoá, chặn mất admin cuối cùng, admin qua mọi kiểm tra vai trò |
| `test_password_change.py` | Tự đổi mật khẩu, admin đặt lại mật khẩu, cả hai đều thu hồi phiên cũ |
| `test_settings_persistence.py` | Lưu cấu hình: khoá API mã hoá khi lưu, lịch sử không bao giờ chứa khoá, restore ghi đúng giá trị .env, khoá không giải mã được (đổi JWT_SECRET) thì bỏ qua chứ không làm sập app |
| `test_tempo.py` | TraceQL dựng từ tham số có kiểm (chặn chèn toán tử qua tên service/namespace), tóm tắt trace (đường chậm nhất, lỗi sâu nhất đứng đầu, thời gian theo service), công cụ trace tôn trọng `K8S_ALLOWED_NAMESPACES` |
| `test_telemetry.py` | Dòng log JSON (kèm exception, trace_id) và `/metrics` có các metric của chat |

`tests/conftest.py` mới là một dòng `TODO`, `tests/integration/` rỗng — nghĩa là **chưa có test nào
chạm cơ sở dữ liệu hay tầng HTTP thật**.

### 3.7 Tracing: OpenTelemetry + Langfuse

Điểm cần hiểu trước: **Langfuse từ bản 3 trở đi chính là OpenTelemetry**, không phải hệ thống song
song. SDK nhận vào một `TracerProvider` có sẵn, gắn `SpanProcessor` của nó vào đó, và lấy `trace_id`
từ chính span context của OTel.

`observability/langfuse_client.py` dựng **một** `TracerProvider` dùng chung cho cả hệ thống và đặt
làm provider toàn cục, rồi cắm Langfuse vào. Sau này thêm instrumentation cho FastAPI hay SQLAlchemy
thì cắm vào cùng provider — mọi thứ nằm chung một trace mà không gây nhiễu, vì bộ lọc mặc định của
Langfuse (`is_default_export_span`) chỉ đẩy lên nó những span có thuộc tính `gen_ai.*` hoặc đến từ
thư viện LLM đã biết; span HTTP và CSDL bị bỏ qua.

`observability/tracing.py` giải bài toán khớp id. Hệ thống ghi `trace_id` xuống bảng `messages`
*trước* khi đồ thị chạy, nên nếu để Langfuse tự sinh id thì sẽ có hai id khác nhau cho cùng một lượt
và `impact.py` sau này không join được. Cách làm: sinh id trước bằng `new_trace_id()` (đúng định dạng
OTel — 128 bit, 32 ký tự hex), rồi ép Langfuse dùng đúng id đó qua
`CallbackHandler(trace_context={"trace_id": ...})`.

Đã kiểm chứng bằng `InMemorySpanExporter` thay cho exporter thật: một lượt chat sinh 4 span
(`ChatGroq`, `tools_condition`, `assistant`, ...) và **cả 4 đều mang đúng trace_id đã lưu xuống CSDL**.

Langfuse tắt thì mọi hàm trả `None` và đồ thị chạy y như cũ. Bật nhưng máy chủ không tới được thì chỉ
ghi một cảnh báo lúc khởi động — đã thử: lượt chat vẫn xong trong 1 giây.

**`LANGFUSE_*` là cấu hình chỉ đọc lúc khởi động, cố tình không cho sửa trên web.** Bên trong SDK,
`LangfuseResourceManager` là singleton khoá theo public key: dựng lại client với cùng khoá nhưng host
khác thì nó trả về đối tượng cũ và **lặng lẽ bỏ qua host mới**. Cho sửa trên giao diện là hứa một
thứ không xảy ra, mà lại không có lỗi nào để lần ra. Đổi trong `.env` rồi khởi động lại backend.

**Đã chạy thật** với Langfuse 4.38 trên `lab1:30400` (25/09/2026): mỗi lượt chat lên Langfuse sau
khoảng 5 giây, đủ cây LangGraph → `assistant` → `ChatGroq` → công cụ, kèm token (vào/ra), độ trễ,
`userId` = email người hỏi và `sessionId` = id hội thoại (khoá `langfuse_user_id`,
`langfuse_session_id`, `langfuse_tags` trong metadata của config đồ thị ở `chat.py`) — nhờ vậy
Langfuse gom được theo người và theo hội thoại. **Chi phí (cost) còn trống**: Langfuse chưa có bảng
giá cho model Groq/Gemini đang dùng; thêm ở mục Models của dự án trên giao diện Langfuse.

Hai cái bẫy đã vấp khi bật:
- **Có khoá chưa đủ, phải có `LANGFUSE_ENABLED=true`** (mặc định `false`). Thiếu dòng này thì
  backend lặng lẽ chạy không trace.
- **`LANGFUSE_BASE_URL` từng bị bỏ qua.** SDK mới đổi tên `LANGFUSE_HOST` → `LANGFUSE_BASE_URL`, còn
  mã chỉ đọc tên cũ nên trace bị gửi về `localhost:3001`. Nay `config.py` nhận cả hai tên.

Máy chủ chạy **Langfuse v4 ở chế độ `events_only`**: các API đọc cũ (`/api/public/traces`,
`/observations`, `/metrics/daily`, `/sessions`) trả 404. Muốn đọc dữ liệu bằng API (ví dụ cho
`impact.py` sau này) phải dùng `/api/public/v2/observations?traceId=...`.

---

### 3.8 Đăng nhập và phân quyền

Ba vai trò: `admin` (chỉnh sửa cấu hình hệ thống, quản lý tài khoản), `engineer` (thêm/sửa/xoá
skill và runbook — khi module đó được viết), `user` (chỉ hỏi đáp và chạy, không tạo/sửa/xoá). Vai
trò cũ (`viewer/operator/admin`) đã được migration đổi tên dữ liệu sang bộ mới, không chỉ đổi tên
biến trong code.

**Cơ chế**: Bearer JWT trong header `Authorization`, KHÔNG dùng cookie (quyết định có cân nhắc —
đơn giản hơn khi debug qua `/docs`, đổi lại token đọc được bằng JS phía client nếu sau này có lỗ XSS
trong phần render Markdown của khung chat). Access token sống 60 phút. Nó có mang `role` nhưng
**không dùng để phân quyền**: `get_current_user` tra lại User từ CSDL ở mỗi request và `require_role`
so với giá trị đó — nên đổi vai trò hay khoá tài khoản có hiệu lực ngay ở request kế tiếp, không
phải đợi token hết hạn. **Admin luôn qua mọi kiểm tra vai trò** (`has_role` trong `deps.py`, bản
tương ứng `hasRole` ở `lib/roles.ts` cho sidebar và `RoleGate`): endpoint sau này ghi
`require_role("engineer")` vẫn mở cho admin mà không cần nhớ liệt kê thêm "admin". Refresh token sống 30 ngày, **xoay vòng**: mỗi lần dùng thì bị thu hồi và cấp lại một cái mới;
dùng lại một refresh token đã bị thu hồi — dấu hiệu bị đánh cắp — sẽ thu hồi LUÔN mọi phiên khác của
người đó.

**Tự đăng ký được**, nhưng `POST /auth/register` luôn ép `role='user'`, không đọc trường role từ
request — tự phong mình làm admin qua endpoint công khai là lỗi kinh điển cần chặn ngay từ thiết kế.
Nâng vai trò phải qua `PATCH /users/{id}` của một admin đang đăng nhập. Tài khoản admin đầu tiên do
`lifespan.py` bootstrap từ `ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` trong `.env` — chỉ chạy
khi CSDL CHƯA có admin nào.

`password_hash` để nullable, dọn đường cho đăng nhập GitHub/Google sau này (chưa làm — chưa có
client ID/secret nào để nối vào, xây `oauth_accounts` trước sẽ thành khung chết).

**Một lỗi thật đã bắt được lúc viết, không phải giả định**: `passlib` (ngừng bảo trì từ 2020) ném
`ValueError` ngay cả với mật khẩu hợp lệ khi chạy cùng `bcrypt>=4.1` — gói đó xoá mất thuộc tính mà
passlib dùng để tự dò phiên bản lúc khởi tạo. Đã bỏ hẳn passlib, gọi thẳng `bcrypt`.

**Một lỗi thật thứ hai**: khi phát hiện refresh token bị dùng lại, code gọi `revoke_all_sessions()`
rồi `raise AuthError` — nhưng dependency `get_session` tự `rollback()` mọi exception bay ra khỏi
endpoint, nên chính hành động thu hồi (việc quan trọng nhất của cả cơ chế chống đánh cắp) bị xoá
theo. Bắt được bằng cách tái hiện đúng kịch bản qua HTTP: dùng lại token cũ, rồi thử token vừa xoay —
lẽ ra phải bị từ chối nhưng vẫn dùng được. Sửa bằng cách `commit()` ngay tại chỗ phát hiện, trước khi
ném lỗi.

Đã kiểm qua HTTP thật (không chỉ unit test): đăng ký ép role, 403 đúng chỗ cho `user` gọi
`PATCH /settings`/`GET /users`, xoay vòng refresh token, phát hiện dùng lại, đăng xuất, khoá tài
khoản chặn được đăng nhập lại. `tests/unit/test_auth_security.py` (11 test, thuần hàm, không CSDL)
giữ lại phần băm mật khẩu + JWT cho hồi quy sau này.

**Đổi mật khẩu** có hai đường, cố tình tách riêng:

- `POST /auth/change-password` — tự đổi, BẮT BUỘC nhập mật khẩu hiện tại (access token bị lộ không
  đủ để chiếm hẳn tài khoản). Đổi xong thu hồi MỌI phiên — lý do phổ biến nhất để đổi mật khẩu là
  nghi đã lộ, khi đó kẻ kia có thể đang giữ refresh token — rồi cấp cặp token mới cho thiết bị hiện
  tại để người đổi không bị văng ra. Nhập sai mật khẩu cũ trả **400 chứ không phải 401**: 401 sẽ
  khiến `lib/api.ts` phía frontend tưởng phiên đã hết và đăng xuất người dùng.
- `POST /users/{id}/reset-password` — admin đặt lại cho người quên mật khẩu, không cần mật khẩu cũ.
  Không dùng được lên chính mình (409) — nếu không, ai nhặt được access token của admin cũng đổi được
  mật khẩu admin đó. Thu hồi mọi phiên của người bị đặt lại.

Đã kiểm bằng trình duyệt thật: đổi mật khẩu xong F5 vẫn còn đăng nhập, mật khẩu cũ bị từ chối, mật
khẩu mới đăng nhập được, admin đặt lại bằng mật khẩu ngẫu nhiên và người đó đăng nhập được ngay.

**Chưa làm**: `app/core/permissions.py` vẫn là khung — nó dành cho một tầng phân quyền MỊN HƠN
(verb + namespace + danger-op blocklist cho thao tác lên cụm), khác với `require_role()` ở
`app/api/deps.py` mà tôi vừa dùng (chỉ so role thô). Hai thứ không thay thế nhau: `require_role`
đủ cho "ai được gọi endpoint nào", nhưng "namespace nào được sửa, thao tác nào bị chặn tuyệt đối"
vẫn cần `permissions.py` khi làm tới pipeline duyệt thao tác.

### 3.9 Tự giám sát: `/metrics` cho Prometheus, log ra stdout

**`/metrics`** (`core/telemetry.py`, gắn ở gốc app chứ không dưới `/api/v1` — proxy Next.js chỉ chuyển
tiếp `/api/v1` nên trình duyệt không với tới được). Gồm:

- Số liệu HTTP theo endpoint từ `prometheus-fastapi-instrumentator` (`http_requests_total`, độ trễ,
  số request đang xử lý). Bỏ qua `/metrics` và health để hai thứ này không lấn át biểu đồ.
- Số liệu riêng của chat, ghi trong `chat.py`: `k8shub_chat_streams_active` (số SSE đang mở — chỉ tăng
  mà không giảm tức là rò rỉ), `k8shub_chat_turns_total{provider,model,outcome}` (ok/error/cancelled),
  `k8shub_chat_turn_duration_seconds`. Label cố tình ít giá trị — không bao giờ gắn theo người
  dùng/hội thoại, vì mỗi giá trị là một time series mới trong Prometheus.

**Chỉ đo sức khoẻ dịch vụ, không đo con AI làm gì — có chủ ý.** Token, chi phí, lời gọi công cụ, theo
người và theo hội thoại đã có trong Langfuse, chi tiết hơn (từng lượt, từng bước). Chép sang
Prometheus là hai nguồn có thể lệch nhau. Prometheus giữ thứ Langfuse không có: luồng có rò rỉ không,
tỉ lệ lỗi, độ trễ — nền cho dashboard Grafana và cảnh báo Alertmanager. (Từng thêm
`k8shub_llm_tokens_total`/`k8shub_tool_calls_total` rồi bỏ vì trùng Langfuse.)

Đã kiểm bằng một lượt chat thật: bộ đếm lượt và độ trễ tăng đúng.

**Log** (`core/logging.py`). Trước đây không ai cấu hình root logger nên mọi `logger.info` của `app.*`
bị nuốt mất — kể cả dòng báo Langfuse bật/tắt. Nay mọi log (của app lẫn uvicorn) ra **stdout**,
`LOG_FORMAT=text` (mặc định, dễ đọc ở console) hoặc `json` (mỗi dòng một object, dùng khi chạy thành
pod để Grafana lọc bằng `| json`). Access log của `/metrics` và health bị lọc bỏ vì chỉ là nhiễu.

**App không tự đẩy log lên Loki — có chủ ý.** Trên lab1, Alloy (`loki.source.kubernetes.pods`) đã đọc
stdout của mọi pod và đẩy vào Loki kèm label `namespace`/`pod`/`container`. Tự đẩy từ app sẽ mất log
đang đệm khi pod chết, mất log khi Loki gián đoạn, thiếu label k8s và trùng với Alloy. Hệ quả: lúc
backend còn chạy trên máy dev thì log chỉ có ở console, chưa vào Loki; lên cụm thì tự có.

**Mức log.** Root luôn ở INFO; `DEBUG=true` chỉ nâng log của `app.*` lên DEBUG — nâng cả root thì mọi
thư viện đều xả log debug (riêng sse-starlette in một dòng cho mỗi token). **Câu SQL chỉ in khi
`DEBUG=true` và `APP_ENV=local`**, bật bằng mức log của `sqlalchemy.engine` chứ không bằng `echo=True`
— `echo` gắn handler riêng của SQLAlchemy nên mỗi câu bị in hai lần. Không bao giờ in SQL ngoài máy
dev: tham số chứa nội dung tin nhắn và phần suy luận của trợ lý, không được lọt vào Loki.
Vì mức log chỉ đặt lúc khởi động, **`DEBUG` đã bị bỏ khỏi trang Cấu hình** (không còn trong
`RUNTIME_EDITABLE`) — sửa trên web mà không có tác dụng gì là hứa suông. `PROMETHEUS_URL` và
`LOKI_URL` cũng bị bỏ khỏi trang: địa chỉ hạ tầng trên lab1, đặt một lần trong `.env`. Trang Cấu hình
giờ chỉ còn hai nhóm LLM và Kubernetes (frontend bỏ nhóm "Observability"). Có test giữ các trường
chỉ-đọc-lúc-khởi-động này không lọt lại lên web.

`METRICS_ENABLED`, `LOG_FORMAT` chỉ đọc lúc khởi động.

---

## 4. Những gì mới là khung

57 file Python (không tính `__init__.py`) và 29 file TypeScript (component, hook, type cho RCA,
skills, approvals, observability) hiện chỉ có một dòng mô tả trách nhiệm kèm `TODO`.
Chúng không vô dụng: mỗi file là một quyết định thiết kế đã chốt về việc "cái gì nằm ở đâu".

**Kubernetes — chưa có gì.** `integrations/k8s/{client,resources,diff,rbac}.py` đều rỗng. Hệ quả dây
chuyền: trợ lý không có công cụ nào tra được cụm, `nl_command` không có gì để lập kế hoạch, RCA
không có nguồn evidence. Đây là nút thắt lớn nhất.

**Pipeline nl_command.** Mới có `agent.py` (đồ thị chat đơn giản), `state.py`, `tools.py`, `prompts/`.
Sáu file còn lại — `intent.py`, `planner.py`, `guardrails.py`, `dry_run.py`, `executor.py`,
`verifier.py` — tức là toàn bộ chuỗi
`intent → plan → dry-run → approval → execute → verify` mà README quảng cáo, đều rỗng. `agent.py`
ghi rõ: chưa gắn checkpointer, và sẽ cần nó khi làm bước duyệt vì lúc đó đồ thị phải dừng giữa chừng
rồi chạy tiếp.

**RCA.** 15 file rỗng: 1 agent, 5 collector (k8s events, logs, metrics, pod state, rollout history),
5 analyzer (CrashLoop, OOM, ImagePull, probe, scheduling), correlator, hypothesis, reporter, triggers.

**Skills / MCP.** 11 file rỗng: schema, registry, loader, executor, mcp_client, runbook và 5 skill
dựng sẵn. Gói `mcp>=1.1.0` đã khai trong `pyproject.toml` nhưng chưa dùng.

**Observability lớp A — còn 5 file rỗng.** `langfuse_client.py` và `tracing.py` đã viết xong
(xem mục 3.7). Còn rỗng: `prompts` (prompt có version), `audit` (audit log append-only),
`impact` (join trace ↔ audit), `evaluation` (dataset + LLM-as-judge), `metrics` (approval rate,
dry-run fail rate). Trong đó `audit.py` là thứ đáng làm sớm nhất — Langfuse chỉ biết LLM *định*
làm gì, còn *cluster thực sự đổi gì* thì không ai ghi lại cả.


**Hạ tầng chung.** `core/security.py` đã xong (mục 3.8). Còn rỗng: `core/permissions.py`
(RBAC mịn theo namespace/verb — khác `require_role`, xem mục 3.8),
`core/exceptions.py`, `workers/{queue,tasks}.py`, `services/{approval,cluster}_service.py`.

**5 router API rỗng**: `clusters`, `approvals`, `rca`, `skills`, `observability`. Chúng đã được mount
vào `api_router` nên hiện ra trong `/docs` nhưng không có endpoint nào.

---

## 5. Vận hành và triển khai

**Hạ tầng nằm trên cụm Kubernetes `lab1`, không dựng bằng Docker ở máy phát triển.**
`deploy/local/docker-compose.yml` đã được xoá: nó dựng Postgres, Redis và Langfuse 2 ở localhost,
trong khi thực tế các thành phần đó đã chạy sẵn trên cụm. Giữ lại chỉ gây hiểu nhầm, nhất là khi
ảnh Langfuse trong đó (`langfuse/langfuse:2`) không tương thích với SDK 4.x đang dùng.

Máy phát triển chỉ chạy backend và frontend, trỏ tới cụm qua `backend/.env`. Máy chỉ có Python 3.14
và **không có `uv`** dù README từng nhắc — đã bổ sung `requirements.txt` và `requirements-dev.txt`
để cài bằng `pip`.

Những gì cụm `lab1` đang có, và chỗ nào còn hụt:

| Thành phần | Trên cụm | Gọi được từ máy dev? |
|---|---|---|
| PostgreSQL (CloudNativePG) | `database/pg-nodeport` | **Có** — `lab1:30432`, đã chạy thật, PG 18.4 |
| Prometheus (kube-prometheus-stack) | `monitoring/.../prometheus` | **Có** — `http://lab1:30090`, đã thử trả 200 |
| Grafana | `monitoring/kps-grafana` | Có — `http://lab1:30300` |
| Tempo v3.0.3 | `tempo/tempo-nodeport` | **Có** — truy vấn `http://lab1:30200`, nhận OTLP ở `30317` (gRPC) / `30318` (HTTP). Chưa có app nào gửi trace thật |
| Loki 3.7.8 | `loki/loki-gateway-nodeport` | **Có** — `http://lab1:31100` (API dưới `/loki/api/v1/...`; `/ready` không qua gateway nên trả 404). Alloy đã gom log mọi pod |
| Langfuse | đã triển khai (v4.38) | **Có** — `http://lab1:30400`, đã nhận trace thật |
| Redis | *chưa có* (cái đang chạy là của Argo CD) | — |

Prometheus trên lab1 **tắt cả remote write lẫn OTLP receiver** (`/api/v1/status/flags`), nên không
đẩy số liệu vào được — nó phải tự scrape. **Có chủ ý không cho Prometheus scrape máy dev** (sẽ phải mở
backend ra mạng); lúc dev xem thẳng `/metrics`. Khi backend chạy thành pod thì thêm một ServiceMonitor
cùng lúc với Deployment — đến lúc đó Prometheus mới có số liệu của app.

Cụm còn sẵn Argo CD (`30080`), Jenkins (`30081`), Alertmanager (`30093`) và Alloy (`31245`) — Alloy
là thứ đang gom log đẩy vào Loki, nên khi cần nguồn log cho RCA thì đường ống đã có sẵn.

Langfuse cần **bản 3 trở lên**: SDK 4.x dựng trên OpenTelemetry và gửi vào `/api/public/otel/v1/traces`,
endpoint bản 2 không có. Trỏ sai bản thì xác thực thất bại lúc khởi động, ứng dụng vẫn chạy nhưng
không có trace nào.

`frontend/Dockerfile` có; **backend chưa có Dockerfile**. `deploy/helm/` vẫn là thư mục rỗng — chưa
có manifest nào để tự triển khai K8s-Hub lên cụm, dù hạ tầng quanh nó thì đã ở đó rồi.

Ba phụ thuộc đã khai trong `pyproject.toml` nhưng chưa dùng dòng nào: `redis`, `pgvector`,
`langgraph-checkpoint-postgres`. Chúng là chỗ đặt trước cho background job, tìm kiếm ngữ nghĩa và
checkpointer của bước duyệt.

Lưu ý về phiên bản: `pyproject.toml` khai sàn rất thấp (`langgraph>=0.2.50`, `langchain-core>=0.3.20`,
`langfuse>=3.0.0`) nhưng thực tế pip kéo về `langgraph 1.2`, `langchain-core 1.6`, `langfuse 4.15`.
Chưa có file khoá phiên bản, nên hai máy cài cách nhau vài tháng có thể ra hai bộ thư viện khác hẳn.

---

## 6. Khoảng trống và rủi ro cần biết

Sắp theo mức độ nên xử lý sớm.

### Đã xử lý trong lần cập nhật này

- **Ghi kết quả bị mất khi client ngắt kết nối.** `sse-starlette` huỷ chính task đang chạy generator,
  nên lệnh ghi trong `finally` bị huỷ ở điểm chờ đầu tiên và tin nhắn kẹt vĩnh viễn ở
  `status='streaming'`. Đã sửa: việc ghi chạy trong `asyncio.Task` riêng, bọc `asyncio.shield`.
- **API không trả số token.** `MessageOut` thiếu `prompt_tokens`/`completion_tokens` nên Pydantic bỏ
  qua, nhìn từ ngoài tưởng hệ thống không đếm được. Dữ liệu vẫn luôn đúng trong CSDL. Đã khai thêm
  hai trường ở cả `schemas/chat.py` và `types/chat.ts`.
- **Race giữa tạo hội thoại và gọi stream.** Từ FastAPI 0.106, phần sau `yield` của dependency chạy
  *sau khi* response đã gửi, nên client nhận 201 trước lúc commit và request kế tiếp gặp 404. Đã
  `commit()` tường minh trong ba endpoint ghi của `chat.py`.
- **Langfuse chưa được nối.** Nay đã nối và chạy thật với máy chủ trên `lab1` (mục 3.7). Trước đó
  backend không gửi trace nào vì `.env` thiếu `LANGFUSE_ENABLED=true` và mã không đọc
  `LANGFUSE_BASE_URL` — cả hai đã sửa.
- **Endpoint cấu hình không có xác thực.** `PATCH /api/v1/settings` từng ghi được cả khoá API mà
  không kiểm tra quyền. Đã khoá bằng `require_role("admin")` (mục 3.8); GET vẫn mở cho mọi vai trò
  đã đăng nhập.
- **Chưa có đăng nhập.** `api/deps.py` từng luôn trả về một tài khoản cục bộ cố định. Đã thay bằng
  JWT thật, 3 vai trò, tự đăng ký, admin quản lý tài khoản (mục 3.8). `require_role()` giờ đã dùng ở
  `settings.py` và `users.py`.
- **Frontend chưa gọi được backend có JWT.** Đã nối xong: trang đăng nhập/đăng ký, lưu token, tự làm
  mới, `AuthGate` chặn `(app)/`, thanh điều hướng lọc theo vai trò (mục 3.8/3.4).
- **Tải lại (F5) bất kỳ trang nào cũng bị đá về /login.** Lúc hydrate, `useSyncExternalStore` trả
  snapshot phía máy chủ ("chưa có phiên") và effect điều hướng trong `AuthGate` chạy ngay ở lần commit
  đó. Chỉ bắt được khi chụp màn hình bằng trình duyệt thật. Sửa: effect đọc thẳng localStorage.
- **Backend tắt cũng bị đá về /login.** Nay chỉ chuyển hướng khi thật sự nhận 401; lỗi mạng hiện
  "không kết nối được máy chủ" kèm nút thử lại, vì phiên vẫn còn.
- **Admin tự khoá mình / hệ thống mất admin cuối cùng.** `PATCH /users/{id}` từng cho phép cả hai —
  sau đó không ai gỡ được từ giao diện, và bootstrap cũng không cứu vì admin bị khoá vẫn tính là "có".
  Nay trả 409 kèm lời giải thích; có 6 test ở `test_user_guard.py`.
- **Không có cách đổi mật khẩu.** Nay có tự đổi (trang Tài khoản) và admin đặt lại (trang Người
  dùng), xem mục 3.8. "Quên mật khẩu" tự phục vụ qua email vẫn chưa có — cần gửi mail, xem rủi ro 2.
- **Trang để trắng và `window.confirm()`.** Trang chưa làm từng `return null`; nút "Đặt lại tất cả" ở
  Cấu hình dùng hộp thoại của trình duyệt; thanh lưu dùng `position: fixed` đè lên sidebar. Đã sửa
  theo quy chuẩn UI/UX mới trong `CLAUDE.md`.
- **Mã nguồn và giao diện lẫn tiếng Việt.** Đã chuyển toàn bộ sang tiếng Anh, kể cả tên định danh
  (ví dụ `EmailDaTonTaiError` → `EmailAlreadyExistsError`, `ThaoTacBiChanError` →
  `OperationBlockedError`, nút đồ thị `tro_ly`/`cong_cu` → `assistant`/`tools`, `useLuuTru` →
  `useLocalStorage`, `laySafeAccessToken` → `getValidAccessToken`). Mã lỗi SSE (`llm_timeout`,
  `llm_rate_limit`, ...) và tên trường trong hợp đồng sự kiện giữ nguyên. Đã kiểm: 132 test pass,
  ruff sạch, `tsc`/`eslint`/`next build` sạch, chụp màn hình Chrome thật không còn chữ tiếng Việt
  nào do mã sinh ra.
- **File thừa.** Đã xoá: hai `prompts/system.md` chỉ có `<!-- TODO -->` (prompt thật ở
  `nl_command/prompts/__init__.py` — hai nơi dễ khiến người sau sửa nhầm file), và khung
  `trace-list`/`trace-detail`/`usage-chart` ở frontend cùng TODO proxy trace/token trong
  `api/v1/observability.py` — những thứ đó làm lại màn hình của Langfuse. Trang Giám sát AI giờ chỉ
  dự kiến phần Langfuse không biết: thay đổi thật trên cụm, tỉ lệ duyệt/từ chối, chấm điểm.
  Gỡ luôn phụ thuộc `structlog` (khai trong `requirements.txt`/`pyproject.toml` nhưng không file
  nào dùng; log JSON chỉ cần thư viện chuẩn, xem mục 3.9).
- **Cấu hình đổi trên web mất sau khi khởi động lại.** Nay lưu xuống Postgres (mục 3.2), có lịch sử
  thay đổi và trang Cấu hình làm lại hoàn toàn (mục 3.4).
- **Sidebar chiếm gần hết màn hình điện thoại.** Dưới 768px sidebar luôn thu gọn thành cột icon 56px
  (trước đây 240px trên màn 390px, còn khoảng 150px cho nội dung).

### Còn tồn tại

**1. Không giới hạn số lần thử đăng nhập/đăng ký.** Không có rate limit hay khoá tạm sau nhiều lần
sai mật khẩu — endpoint `/auth/login` dò mật khẩu bằng vét cạn được nếu ai đó cố tình.

**2. Chưa có "quên mật khẩu" tự phục vụ.** Người quên mật khẩu phải nhờ admin đặt lại. Làm luồng tự
phục vụ (gửi liên kết qua email) cần hạ tầng gửi mail, hiện chưa có.

**3. Không xác minh email lúc đăng ký.** Ai cũng đăng ký được với bất kỳ email nào gõ đúng định
dạng, kể cả email không thuộc về mình.

**4. `require_tool_calling()` viết xong nhưng chưa gọi.** Chính docstring của nó ghi "CHƯA ĐƯỢC GỌI".
Chọn một model Groq nhỏ không hỗ trợ gọi công cụ thì lỗi chỉ lộ ra khi người dùng đã chat.

**5. Không có test tích hợp.** Auth đã kiểm bằng tay qua HTTP thật (mục 3.8) trong lúc phát triển,
nhưng đó là việc làm một lần, không lặp lại được. `conftest.py` rỗng nên toàn bộ tầng HTTP, tầng CSDL
và các endpoint hội thoại/đăng nhập chưa có test tự động nào chạm tới.

**6. `history_to_messages()` bỏ hết tool call của lượt trước.** Đây là lựa chọn có chủ ý và đã ghi rõ
lý do (gửi thiếu vế là nhà cung cấp trả lỗi; kết quả cũ thường đã lỗi thời), nhưng hệ quả là trợ lý
không nhớ nó đã tra gì ở lượt trước. Khi công cụ tra cụm xuất hiện, cần xem lại quyết định này.

**Dữ liệu cũ trong CSDL vẫn tiếng Việt.** Tên hiển thị tài khoản (ví dụ admin "Người dùng cục bộ"),
tiêu đề và nội dung hội thoại cũ được lưu trước khi đổi ngôn ngữ nên vẫn hiện tiếng Việt; mã không
còn sinh ra chữ tiếng Việt. Hội thoại trống tạo trước khi đổi (tiêu đề "Hội thoại mới") sẽ không tự
đặt tên theo câu hỏi đầu, vì tiêu đề mặc định nay là "New conversation". Sửa tên trong trang Người
dùng / Tài khoản, hoặc xoá hội thoại cũ, nếu muốn giao diện sạch hẳn.

---

## 7. Gợi ý thứ tự làm tiếp

Xếp theo mức độ mở khoá cho phần còn lại:

1. **`integrations/k8s/client.py` + vài công cụ chỉ đọc** (`list_pods`, `describe`, `logs`,
   `query_metrics`) gắn vào `get_tools()`, theo đúng khuôn của công cụ trace đã có (client → tóm tắt
   → tool, tham số có kiểm, tôn trọng namespace được phép). Đây là nút thắt: xong bước này thì khung
   chat lập tức có giá trị thật, và RCA có nguồn evidence. Song song phía hạ tầng: bật Beyla để Tempo
   có trace thật.
2. **Bảng giá model trong Langfuse** để có cột chi phí — tracing đã chạy thật, chỉ còn thiếu giá cho
   model Groq/Gemini (khai trên giao diện Langfuse, không cần sửa mã).
3. **`audit.py`** — bảng append-only. Cần có trước khi có bất kỳ thao tác ghi nào lên cụm, và là
   thứ Langfuse không bao giờ thay được: nó chỉ biết LLM *định* làm gì.
4. **Pipeline duyệt** (`planner` → `guardrails` → `dry_run` → approval gate → `executor` → `verifier`).
   Hợp đồng sự kiện SSE cho phần này đã định nghĩa xong, nên frontend sẽ lắp vào nhanh. Guardrail nên
   dùng `require_role` đã có sẵn để chặn `user` khỏi bước duyệt — chỉ `admin`/`engineer` mới được.
5. **RCA**, dùng lại các collector đã có từ bước 1.
6. **Rate limit cho `/auth/login` và `/auth/register`** (rủi ro số 1 ở mục 6) — việc nhỏ, đáng làm
   sớm trước khi có ai đó thử vét cạn mật khẩu.

Lớp C (tự giám sát) **đã làm** (mục 3.9); việc còn lại là thêm ServiceMonitor khi backend chạy thành
pod. Không bắc cầu số liệu từ Langfuse sang
Prometheus: thứ chuyển được (token, cost) thì Langfuse hiển thị tốt hơn.

---

*Báo cáo này đọc mã ở trạng thái nhánh `main`. Mọi nhận định về "chưa có" đều dựa trên nội dung file
tại thời điểm đọc, không dựa vào README hay kế hoạch.*

*Giữ cho tài liệu này khớp với mã là quy tắc thường trực của dự án — xem `CLAUDE.md` và skill
`cap-nhat-hien-trang`.*
