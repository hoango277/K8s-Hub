# Kế hoạch: nối RCA với Chat và Skills

*Ngày 10/11/2026. Người dùng chọn từ danh sách gợi ý: "nút Ask in chat trên trang chẩn đoán để hỏi tiếp với sẵn ngữ
cảnh; bước tiếp theo của RCA gợi ý skill phù hợp (CrashLoop thì gợi ý diagnose-crashloop)". Đây là **kế hoạch**;
trạng thái chạy thật ghi ở `docs/hien-trang-codebase.md`.*

## Tiến độ

| Hạng mục | Trạng thái |
|---|---|
| 1. Hội thoại gắn với một chẩn đoán (`chat_threads.rca_run_id`, migration, API tạo hội thoại) | **Xong** (10/11/2026) — migration `7e2a9c4d1b60` đã áp vào CSDL dev |
| 2. Ngữ cảnh cho trợ lý: mục CONVERSATION CONTEXT trong system prompt + tool `get_diagnosis` | **Xong** |
| 3. Skill gợi ý theo loại sự kiện (`metadata.rca-events` trong SKILL.md, gắn cho 3 skill mẫu) | **Xong** |
| 4. Giao diện: "Ask in chat", skill gợi ý trên thẻ nguyên nhân, dải ngữ cảnh + gợi ý câu hỏi trong chat | **Xong** — "Ask in chat" dùng lại hội thoại đã có của run thay vì tạo thêm |
| 5. Test + kiểm trên trình duyệt | **Xong** — 14 test; Chrome thật + một lượt chat thật (Gemini). Phát sinh: model trả lời rỗng → thêm lớp hỏi lại một lần (`agent.py`, 3 test) |

## 1. Hội thoại gắn với một chẩn đoán

- Cột mới `chat_threads.rca_run_id` (UUID, FK `rca_runs.id`, `ON DELETE SET NULL`; run không bao giờ bị xoá nhưng
  khoá ngoại vẫn phải có hành vi rõ ràng).
- `POST /chat/threads` nhận thêm `rca_run_id`. Backend kiểm **đúng quy tắc xem run của API RCA** (`user` chỉ thấy run
  của mình và run hệ thống alert/scan; engineer+ thấy hết) — không thấy thì 404 "Diagnosis not found", không để lộ
  run có tồn tại hay không. Tiêu đề mặc định "Diagnosis: <đối tượng>" (không bị câu hỏi đầu ghi đè).
- `ThreadOut` trả `rca_run_id` để giao diện biết hội thoại thuộc chẩn đoán nào.

## 2. Ngữ cảnh cho trợ lý — chống prompt injection là ràng buộc chính

Bằng chứng của RCA lấy từ log, annotation, tên pod… — dữ liệu do người điều khiển workload viết. Nếu chép thẳng vào
system prompt, một dòng log kiểu "SYSTEM NOTICE: …" sẽ nằm ở vị trí có quyền cao nhất. Vì vậy chia hai phần:

- **System prompt** (mỗi lượt của hội thoại đó) chỉ thêm dữ liệu do K8s-Hub sinh: id run, namespace/đối tượng (đã
  kiểm DNS-1123 lúc tạo run), cửa sổ thời gian, và lời dặn "gọi `get_diagnosis` để đọc kết quả trước khi trả lời".
- **Nội dung chẩn đoán** đi qua tool `get_diagnosis(run_id)` (nhóm Diagnosis, chỉ đọc, đăng ký trong registry) — kết
  quả được bọc `<tool_output trust="untrusted">` như mọi dữ liệu cụm (`injection.py`). Tool kiểm quyền xem run theo
  vai trò của người đang chat. Nội dung: mục tiêu + cửa sổ, tóm tắt AI, top nguyên nhân (hạng, loại, đối tượng, điểm,
  chuỗi, verdict + lý do của AI, bước tiếp theo, một bằng chứng), skill gợi ý, bản sửa (đề xuất được hay chỉ là lời
  khuyên, đã đề xuất chưa), khoảng trống dữ liệu, link `/rca/<id>`. Giới hạn ~5.000 ký tự.
- Trợ lý cũng gọi được `get_diagnosis` với id bất kỳ người dùng dán vào (vd. link từ `diagnose_incident`).

## 3. Skill gợi ý theo loại sự kiện

- Chuẩn Agent Skills có trường tuỳ chọn `metadata` (map chuỗi → chuỗi, client tự định nghĩa khoá). Dùng khoá
  `rca-events`: danh sách loại sự kiện RCA, cách nhau bằng dấu phẩy hoặc dấu cách:
  ```yaml
  metadata:
    rca-events: CrashLoop, RestartSpike, OOMKilled, ProbeFailed
  ```
  Skill export sang agent khác vẫn hợp lệ (agent khác bỏ qua `metadata`).
- Parser kiểm từng tên có trong `model.EVENT_TYPES`; sai thì báo lỗi kèm danh sách tên đúng (gõ nhầm sẽ âm thầm
  không bao giờ khớp nếu không kiểm).
- Gợi ý cho một nguyên nhân: skill **đang bật** có loại khớp với bất kỳ sự kiện nào trong chuỗi của nó (gốc trước —
  rollout gây CrashLoop vẫn gợi ý `diagnose-crashloop`), tối đa 2. Tính **lúc đọc run**, nên skill gắn thêm sau vẫn
  hiện cho run cũ.
- Gắn cho 3 skill mẫu: `diagnose-crashloop` (CrashLoop, RestartSpike, OOMKilled, ProbeFailed, ContainerConfigError),
  `investigate-slow-requests` (LatencySpike, ErrorRateSpike, DownstreamErrors), `namespace-health-check`
  (ReplicasUnavailable, PodNotReady, RolloutStuck, MemoryNearLimit, MemoryLeak, CpuThrottling).

## 4. Giao diện

- **Trang chi tiết chẩn đoán:** nút "Ask in chat" cạnh "Run again now" → tạo hội thoại gắn run → mở `/chat?thread=<id>`.
  Trên mỗi thẻ nguyên nhân, dưới "Next steps": dòng skill gợi ý (link tới trang skill) và nút "Investigate in chat"
  — mở hội thoại gắn run và **soạn sẵn** câu "Use the <skill> skill to investigate cause #n (…)" trong ô nhập.
  Không tự gửi: một lượt chat tốn token (hạn mức miễn phí nhỏ), người dùng tự bấm gửi.
- **Chat:** mở được hội thoại từ `?thread=<id>` (rồi xoá tham số khỏi URL); hội thoại gắn run có dải ngữ cảnh trên
  đầu ("About the diagnosis of … · Open diagnosis"); màn hình trống của hội thoại đó gợi ý câu hỏi riêng cho chẩn
  đoán thay cho gợi ý chung.

## Không làm

- Tự gửi câu hỏi khi mở chat; chép cả đồ thị vào prompt; để LLM chọn skill gợi ý (bảng khớp tất định, giải thích được).

## Kiểm tra

- Test: parser `metadata.rca-events` (đúng/sai tên), khớp skill theo chuỗi + skill tắt không hiện, `get_diagnosis`
  (quyền theo vai trò, nội dung, giới hạn độ dài, bọc untrusted vì nằm trong registry), system prompt có/không mục
  ngữ cảnh, API tạo hội thoại với run không được xem → 404.
- Typecheck + lint; xem trên Chrome thật: nút trên trang chẩn đoán, dải ngữ cảnh, câu soạn sẵn. Một lượt chat thật để
  xác nhận trợ lý gọi `get_diagnosis` (tốn token — làm một lần).
