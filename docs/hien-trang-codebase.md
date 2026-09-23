# Hiện trạng codebase K8s Hub

*Báo cáo đọc mã, cập nhật ngày 23/09/2026. Mô tả những gì ĐANG CÓ trong kho, không phải kế hoạch.*

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
| Trang Cấu hình trên web | **Chạy được** |
| Kết nối Kubernetes | Chưa có dòng mã nào |
| RCA | Chỉ có khung file |
| Skills / MCP / runbook | Chỉ có khung file |
| Langfuse / audit log / đo lường | Chỉ có khung file |
| Đăng nhập, phân quyền | Chưa có — mọi thao tác chạy dưới một tài khoản cục bộ |

Về khối lượng: backend có ~4.100 dòng Python, nhưng khoảng **65 file chỉ chứa một dòng docstring
kèm `TODO`**. Frontend có ~30 component/hook/type ở dạng khung rỗng (`return null`). Nghĩa là cấu
trúc dự án đã được nghĩ xong và đóng cọc sẵn; phần thịt mới đắp vào một nhánh.

Điểm mạnh rõ rệt của kho mã này là **chất lượng phần đã làm**: gần như mọi file đã hoàn thiện đều
có docstring giải thích *vì sao* làm như vậy, kể cả những cái bẫy đã vấp phải (streaming bị `rewrites`
của Next.js gom lại, `useSyncExternalStore` với `subscribe` rỗng, pgbouncer không dùng được prepared
statement). Đó là tài liệu có giá trị hơn hầu hết README.

---

## 2. Bản đồ kho mã

```
K8s-Hub/
├── backend/          FastAPI + LangGraph + SQLAlchemy async
│   ├── app/api/v1/   8 router: chat, settings, health (thật) + 5 router rỗng
│   ├── app/core/     config.py (791 dòng, trung tâm hệ thống) + 4 file khung
│   ├── app/db/       models users/chat_threads/messages/tool_calls + session
│   ├── app/integrations/  llm/ (xong) · k8s, prometheus, loki (khung)
│   ├── app/modules/  nl_command (một phần) · rca, skills, observability (khung)
│   ├── app/schemas/  events.py, chat.py (xong) + 5 file khung
│   ├── app/services/ thread_service.py (xong) + 2 file khung
│   ├── migrations/   2 revision Alembic
│   └── tests/unit/   6 file test
├── frontend/         Next.js 16 + React 19 + Tailwind v4 + TanStack Query
│   └── src/          chat/ và settings/ làm thật; rca, skills, approvals, observability rỗng
├── deploy/local/     docker-compose: Postgres(pgvector), Redis, Langfuse
├── deploy/helm/      thư mục rỗng
└── docs/             3 file kế hoạch .xlsx
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
- **Đóng tab giữa chừng vẫn lưu được phần đã nói.** Khối `finally` trong `chat.py` và trong
  `streaming.py` đều chạy khi bị huỷ.
- **Tách riêng phần suy luận (thinking) khỏi câu trả lời.** `_reasoning_of()` xử lý ba dạng khác
  nhau: `reasoning_content` của Groq, khối `thinking` của Anthropic, và cờ `thought=True` của Gemini.
  Trộn hai thứ vào nhau là nguy hiểm vì suy luận chứa cả kết luận sai mà mô hình tự bác bỏ.
- **Hợp đồng sự kiện SSE được kiểm bằng test.** `tests/unit/test_events_contract.py` đọc thẳng
  `frontend/src/types/events.ts` và so với `app/schemas/events.py`, nên sửa một bên mà quên bên kia
  thì test đỏ.

Schema sự kiện đã định nghĩa sẵn 12 loại: `token`, `thinking`, `step`, `tool_call_start/end`,
`plan`, `approval_required`, `approval_resolved`, `verify_result`, `error`, `done`, `heartbeat`.
Mới 6 loại đầu được phát ra thật; nhóm `plan`/`approval_*`/`verify_result` là hợp đồng dành sẵn cho
pipeline duyệt thao tác chưa làm.

### 3.2 Tầng cấu hình — phần được thiết kế kỹ nhất

`backend/app/core/config.py` (791 dòng) là file quan trọng nhất trong kho. Nó làm bốn việc:

1. **Hai tầng cấu hình chồng lên nhau**: `.env` (cứng, đọc một lần lúc khởi động) + phần người dùng
   đổi trên web (nóng). Kết quả là `settings` — một proxy luôn hỏi lại giá trị mới nhất, nên module
   nào `from app.core.config import settings` cũng không bị cầm object cũ.
2. **Danh sách trắng những gì đổi được lúc chạy**: `RUNTIME_EDITABLE` (16 trường) và
   `RUNTIME_EDITABLE_SECRETS` (5 khoá API — ghi vào được nhưng không bao giờ đọc ra). `DATABASE_URL`,
   `JWT_SECRET` cố tình không nằm trong đó.
3. **Kiểm tra trước khi áp**: sai một trường thì cả lô bị từ chối và cấu hình đang chạy giữ nguyên.
4. **Cơ chế `on_reload()`**: module nào có bộ nhớ đệm dựng từ cấu hình thì đăng ký hàm dọn đệm.
   Hiện có 4 nơi dùng: bộ đệm model LLM, engine CSDL, danh mục model, tài khoản cục bộ.

Đặc tả nhà cung cấp LLM (`ProviderConfig`) là chỗ hấp thụ mọi khác biệt giữa Groq / Google /
Anthropic: `param_map` ánh xạ tên tham số chuẩn sang tên thật (Gemini gọi `max_tokens` là
`max_output_tokens`, Anthropic gọi `timeout` là `default_request_timeout`). Thêm một nhà cung cấp
mới chỉ cần thêm một mục JSON vào biến `LLM_PROVIDERS` trong `.env`, **không sửa code**.

`catalog.py` đi thêm một bước: hỏi thẳng API của nhà cung cấp để lấy danh sách model, thay vì viết
cứng một danh sách sẽ sai trong vài tháng. Phần lọc model không-phải-chat (`whisper`, `orpheus`,
`llama-prompt-guard`) dựa trên trường dữ liệu trả về chứ không dựa vào tên model.

### 3.3 Lưu trữ

Bốn bảng đã có model và migration:

| Bảng | Vai trò |
|---|---|
| `users` | Chỗ gắn chủ sở hữu. Chưa có đăng nhập, nhưng có sẵn để sau này không phải vá dữ liệu cũ |
| `chat_threads` | Một hội thoại. `last_message_at` tách khỏi `updated_at` để sửa tiêu đề không làm hội thoại nhảy lên đầu |
| `messages` | Có `reasoning`, `trace_id`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `latency_ms` |
| `tool_calls` | Bảng riêng chứ không nhét JSON vào `messages`, để thống kê "công cụ nào hay lỗi nhất" chỉ cần một câu truy vấn |

Mọi quan hệ đặt `lazy="raise"` — đọc quan hệ chưa nạp sẵn sẽ báo lỗi ngay thay vì lặng lẽ bắn thêm
truy vấn giữa luồng bất đồng bộ. Quy ước đặt tên ràng buộc cố định trong `db/base.py` để Alembic
sinh tên ổn định.

`db/session.py` xử lý sẵn các bẫy của Supabase/pgbouncer: tắt prepared statement khi đi qua bộ gộp,
bắt buộc SSL với máy chủ ngoài, bỏ `pool_pre_ping` khi độ trễ cao, `pool_size=5`.

### 3.4 Giao diện

Chạy thật: **trang Trò chuyện** và **trang Cấu hình**.

- `chat-panel.tsx` — danh sách hội thoại, tạo/xoá, chọn model, khung chat streaming, nhớ hội thoại
  đang mở qua localStorage.
- `message-item.tsx`, `thinking-block.tsx`, `tool-call-card.tsx`, `markdown.tsx` — hiển thị câu trả
  lời, khối suy luận có đếm thời gian, thẻ gọi công cụ kèm tham số và kết quả.
- `model-picker.tsx` + `use-models.ts` — chọn nhà cung cấp và model cho riêng một lượt chat; lựa
  chọn được gửi kèm request và công cụ `system_info` đọc lại từ metadata để trợ lý khai đúng về
  chính nó.
- `settings-form.tsx` + `field-input.tsx` — dựng form tự động từ mô tả trường do backend trả về
  (`GET /settings`), phân biệt trường bí mật, hiện giá trị gốc trong `.env` và trạng thái "đang bị
  ghi đè".

Thanh điều hướng đã có đủ 6 mục, nhưng 4 mục (Chẩn đoán, Kỹ năng, Chờ duyệt, Giám sát AI) dẫn tới
trang `return null`.

### 3.5 Công cụ trợ lý đang có

Đúng **hai** công cụ, cả hai đều chỉ đọc:

- `system_info` — hệ thống đang chạy model nào, chế độ thực thi nào, namespace nào được phép.
- `current_time` — thời điểm hiện tại UTC.

`tools.py` ghi rõ ba ranh giới an toàn cho người thêm công cụ sau này: chỉ được đọc, không nhận chuỗi
lệnh thô (`run_kubectl(cmd)` bị cấm), và mô tả công cụ phải rõ vì đó là thứ mô hình đọc để quyết định.

### 3.6 Kiểm thử

6 file test đơn vị, không cần mạng và không cần CSDL:

| File | Kiểm gì |
|---|---|
| `test_chat_streaming.py` | Lớp dịch sự kiện LangGraph → SSE (chỗ dễ vỡ nhất khi nâng phiên bản) |
| `test_events_contract.py` | Backend và frontend khớp nhau |
| `test_llm_provider.py` | Ánh xạ tham số giữa các nhà cung cấp + đổi nóng cấu hình |
| `test_model_catalog.py` | Đọc danh sách model, dùng dữ liệu mẫu lấy từ phản hồi thật |
| `test_chat_tools.py` | Gọi công cụ thật (viết ra sau khi có lỗi lọt lưới) |
| `test_chat_history.py` | Đặt tiêu đề + nạp lịch sử làm ngữ cảnh |

`tests/conftest.py` mới là một dòng `TODO`, `tests/integration/` rỗng — nghĩa là **chưa có test nào
chạm cơ sở dữ liệu hay tầng HTTP thật**.

---

## 4. Những gì mới là khung

Khoảng 65 file Python và 30 file TypeScript hiện chỉ có một dòng mô tả trách nhiệm kèm `TODO`.
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

**Observability lớp A.** 7 file rỗng: `langfuse_client`, `tracing`, `prompts`, `audit`, `impact`,
`evaluation`, `metrics`. `chat.py` đã sinh `trace_id` và lưu vào bảng `messages`, nhưng **không có gì
gửi trace đó sang Langfuse** — biến `LANGFUSE_ENABLED` hiện chưa được đọc ở đâu cả.

**Observability lớp C.** `core/telemetry.py` mới là docstring: chưa có `/metrics`, chưa có structlog.

**Hạ tầng chung.** `core/security.py` (JWT), `core/permissions.py` (RBAC), `core/logging.py`,
`core/exceptions.py`, `workers/{queue,tasks}.py`, `services/{approval,cluster}_service.py` — rỗng.

**5 router API rỗng**: `clusters`, `approvals`, `rca`, `skills`, `observability`. Chúng đã được mount
vào `api_router` nên hiện ra trong `/docs` nhưng không có endpoint nào.

---

## 5. Vận hành và triển khai

`deploy/local/docker-compose.yml` dựng 4 service: Postgres (ảnh `pgvector/pgvector:pg16`), Redis,
Postgres riêng cho Langfuse, và Langfuse 2 (cổng 3001).

`frontend/Dockerfile` có; **backend chưa có Dockerfile**. `deploy/helm/` là thư mục rỗng — chưa có
manifest nào để tự triển khai lên Kubernetes.

Ba phụ thuộc đã khai trong `pyproject.toml` nhưng chưa dùng dòng nào: `redis`, `pgvector`,
`langgraph-checkpoint-postgres`. Chúng là chỗ đặt trước cho background job, tìm kiếm ngữ nghĩa và
checkpointer của bước duyệt.

---

## 6. Khoảng trống và rủi ro cần biết

Sắp theo mức độ nên xử lý sớm.

**1. Endpoint cấu hình không có xác thực.** `PATCH /api/v1/settings` ghi được cả khoá API
(`GROQ_API_KEY`, `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, khoá Langfuse) mà không kiểm tra quyền —
chính file đó đã ghi `TODO` về việc này. Chạy local thì không sao; đưa lên bất kỳ máy nào người khác
chạm được là mất khoá. Cần chặn trước khi deploy ra ngoài localhost.

**2. Chưa có đăng nhập.** `api/deps.py` luôn trả về một tài khoản cục bộ
(`local@k8s-hub.dev`, vai trò `admin`). Hàm `require_role()` đã viết sẵn nhưng chưa dùng ở đâu. Mọi
hội thoại thuộc về cùng một người.

**3. Cấu hình đổi trên web mất sau khi khởi động lại.** `MemoryOverrideStore` chỉ giữ trong bộ nhớ,
và `set_override_store()` chưa được gọi ở `lifespan`. Người dùng nhập khoá API trên giao diện,
restart backend là mất. Cần một lớp lưu xuống Postgres — chỗ cắm đã có sẵn (`OverrideStore` Protocol).

**4. Langfuse là lời hứa chưa thực hiện.** README, `docker-compose`, `.env.example` và cột
"Observability lớp A" đều nói về Langfuse; thực tế `trace_id` được sinh ra và lưu nhưng không đi đâu
cả. Frontend cũng đã có `NEXT_PUBLIC_LANGFUSE_HOST` và component `trace-link.tsx` (rỗng). Đây là
khoảng cách giữa tài liệu và mã cần nói rõ khi báo cáo đồ án.

**5. Hai nguồn sự thật cho system prompt.** Prompt thật nằm trong
`app/modules/nl_command/prompts/__init__.py`, trong khi `prompts/system.md` và
`rca/prompts/system.md` chỉ chứa `<!-- TODO -->`. Nên xoá hoặc hợp nhất trước khi có người sửa nhầm
file `.md` rồi tưởng đã đổi prompt.

**6. `require_tool_calling()` viết xong nhưng chưa gọi.** Chính docstring của nó ghi "CHƯA ĐƯỢC GỌI".
Chọn một model Groq nhỏ không hỗ trợ gọi công cụ thì lỗi chỉ lộ ra khi người dùng đã chat.

**7. Không có test tích hợp.** `conftest.py` rỗng nên toàn bộ tầng HTTP, tầng CSDL và các endpoint
hội thoại chưa có test nào chạm tới.

**8. `history_to_messages()` bỏ hết tool call của lượt trước.** Đây là lựa chọn có chủ ý và đã ghi rõ
lý do (gửi thiếu vế là nhà cung cấp trả lỗi; kết quả cũ thường đã lỗi thời), nhưng hệ quả là trợ lý
không nhớ nó đã tra gì ở lượt trước. Khi công cụ tra cụm xuất hiện, cần xem lại quyết định này.

---

## 7. Gợi ý thứ tự làm tiếp

Xếp theo mức độ mở khoá cho phần còn lại:

1. **`integrations/k8s/client.py` + vài công cụ chỉ đọc** (`list_pods`, `describe`, `logs`) gắn vào
   `get_tools()`. Đây là nút thắt: xong bước này thì khung chat lập tức có giá trị thật, và RCA có
   nguồn evidence.
2. **Lớp lưu override xuống Postgres** + chặn quyền cho `PATCH /settings`. Hai việc nhỏ, gỡ được rủi
   ro số 1 và số 3.
3. **Nối Langfuse** (`langfuse_client.py` + `tracing.py`) — chỉ cần gắn `CallbackHandler` vào config
   của LangGraph là có ngay trace, vì `trace_id` đã được sinh sẵn.
4. **`audit.py`** — bảng append-only. Cần có trước khi có bất kỳ thao tác ghi nào lên cụm.
5. **Pipeline duyệt** (`planner` → `guardrails` → `dry_run` → approval gate → `executor` → `verifier`).
   Hợp đồng sự kiện SSE cho phần này đã định nghĩa xong, nên frontend sẽ lắp vào nhanh.
6. **RCA**, dùng lại các collector đã có từ bước 1.

---

*Báo cáo này đọc mã ở trạng thái nhánh `main`. Mọi nhận định về "chưa có" đều dựa trên nội dung file
tại thời điểm đọc, không dựa vào README hay kế hoạch.*
