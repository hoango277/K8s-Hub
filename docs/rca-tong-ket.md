# Tổng kết RCA của K8s-Hub — kiểm thử, so sánh, hướng cải thiện

*Viết ngày 07/10/2026. Số liệu lấy từ `backend/rca_eval/results/` (chạy trên cụm lab1). Thiết kế và kế
hoạch: `docs/ke-hoach/rca-groot.md`; những gì đang chạy: `docs/hien-trang-codebase.md` mục 3.12.*

## 1. RCA của K8s-Hub làm gì

Chẩn đoán nguyên nhân gốc theo hướng **Groot (eBay, ASE'21)**: đồ thị sự kiện + luật nhân quả + xếp hạng,
LLM chỉ đứng ở cuối để kiểm chứng và viết báo cáo.

```
API Kubernetes ─┐
Prometheus ─────┤   7 detector        65 luật nhân quả       PageRank cá nhân hoá      LLM (≤ 4 tool đọc)
Loki (log+events)┼─▶ → sự kiện có ─▶ → đồ thị sự kiện ─▶ → top-3 + chuỗi nhân quả ─▶ → kiểm chứng + báo cáo
Tempo ──────────┤   bằng chứng ≤300   (không luật,          (tất định, ~1–2 giây)     → validator tất định
bảng approvals ─┘   ký tự            không cạnh)                                      → đề xuất sửa qua phê duyệt
```

- **Kích hoạt:** nút trên trang Diagnosis, tool chat `diagnose_incident`, webhook Alertmanager (đã chạy
  thật từ lab1), quét định kỳ.
- **Nguyên tắc:** LLM không bao giờ nhận log/metric thô; mọi thứ AI trả về đi qua validator; bản sửa chỉ
  được chọn trong danh sách tính sẵn và luôn chờ engineer duyệt.

## 2. Kết quả kiểm thử

### 2.1 Tám kịch bản lỗi có nhãn (lần chạy sạch, `20261007-090958`)

Mỗi kịch bản: dựng workload khoẻ trong namespace `rca-lab` → gây đúng một lỗi → chờ triệu chứng → chẩn
đoán → dọn. So với **k8sgpt v0.4.39** (CNCF) chạy analyzer tất định trên cùng cụm, cùng thời điểm.

| Kịch bản | Nguyên nhân thật | K8s-Hub (hạng của nguyên nhân thật) | k8sgpt (có finding nào nhắc tới?) |
|---|---|---|---|
| bad-image | Rollout đổi sang image không tồn tại | **1** | có — "Back-off pulling image…" |
| oom | Container cấp phát vượt memory limit | **1** | có — "termination reason is OOMKilled" |
| bad-config | ConfigMap bị sửa thành giá trị app từ chối | **1** | **không** — chỉ thấy "exit code 1", "0 available" |
| missing-key | Rollout tham chiếu key ConfigMap không có | **1** | có — "couldn't find key KEY_MISSING" |
| bad-probe | Rollout đổi readiness probe sang path 404 | **1** | có — "Readiness probe failed… 404" |
| too-big | Rollout đòi CPU vượt sức node | **1** | có — "Insufficient cpu" |
| pvc-pending | PVC dùng StorageClass không tồn tại | **1** | có — "storageclass … not found" |
| scale-zero | Thay đổi đã duyệt qua K8s-Hub scale về 0 | **1** | **không** — chỉ thấy "Service has no endpoints" |

| Chỉ số | K8s-Hub RCA (phần tất định) | k8sgpt analyzers |
|---|---|---|
| Top-1 | **8/8** | — (không xếp hạng) |
| Top-3 | **8/8** | — |
| Nhắc tới nguyên nhân ở đâu đó | 8/8 | 6/8 |
| Thời gian trung bình | 1,3 giây | < 2 giây |
| Token LLM | 0 | 0 |

**Đọc kết quả cho đúng:**
- Cách chấm k8sgpt **dễ dãi** (chỉ cần một finding bất kỳ chứa từ khoá). k8sgpt là công cụ *liệt kê
  triệu chứng theo từng đối tượng*: nó không xếp hạng, không biết thứ tự thời gian, không có khái niệm
  "thay đổi". Hai ca nó trượt đều là ca mà **nguyên nhân là một thay đổi** (sửa ConfigMap, scale qua phê
  duyệt) chứ không phải một trạng thái lỗi — đúng chỗ mạnh của cách tiếp cận Groot.
- Ở các ca nguyên nhân là rollout (bad-image, missing-key, bad-probe, too-big), k8sgpt chỉ ra **triệu
  chứng** (image không kéo được, thiếu key…), còn K8s-Hub chỉ ra **thay đổi gây ra nó** (rollout nào,
  đổi image gì từ đâu sang đâu) và đề xuất được bản sửa (rollback về image cũ).
- 8/8 là trên **8 lỗi đơn, môi trường sạch, nhãn do chính tác giả đặt** — kết quả tốt nhưng chưa nói
  được độ chính xác trên sự cố thật phức tạp (xem mục 4).

### 2.2 Phần có LLM (mẫu nhỏ — chưa đủ để kết luận)

Hạn mức miễn phí hết trong ngày (Groq `gpt-oss-120b`: 200.000 token/ngày; Gemini `gemini-2.5-flash`: 20
request/ngày), và hai lần chạy bị chồng thời gian nhau, nên phần này chỉ dùng các ca chạy xong trọn vẹn:

| | Báo cáo AI của K8s-Hub | Agent LLM + tool (kiểu HolmesGPT/kubectl-ai) |
|---|---|---|
| Chọn đúng nguyên nhân | 10/10 ca có báo cáo hoàn tất (Groq + Gemini) | 6/6 ca chạy xong |
| Thời gian | 1–2 giây xếp hạng + 4–21 giây báo cáo | 11–169 giây |
| Token mỗi ca | ~4.000–11.000 | ~12.000–31.000 |
| Khi LLM lỗi/hết quota | vẫn còn kết quả xếp hạng | không có kết quả gì |

Baseline là **chính trợ lý chat của K8s-Hub** với cùng bộ tool đọc (bỏ `diagnose_incident` và tool ghi) —
cùng kiến trúc "LLM + vòng gọi tool" với HolmesGPT và kubectl-ai, nhưng **không phải chạy chính các công cụ
đó**. Trên lỗi đơn giản, agent LLM cũng tìm ra nguyên nhân; khác biệt đo được là **chi phí (2–4 lần
token), thời gian (5–80 lần) và độ bền** (hết quota = không có câu trả lời).

### 2.3 Sự cố thật trên lab1

- **Alloy crash-loop** (namespace `monitoring`): detector ra CrashLoop, MemoryNearLimit 94%, exit 137,
  mẫu log lỗi mới "dropping data" — đúng chẩn đoán đã xác nhận bằng tay (OOM ở limit 1Gi).
- **Langfuse** (namespace `langfuse`): xếp hạng ra probe timeout + worker crash-loop; AI kiểm chứng bằng
  log và chỉ ra gốc chung là **mất kết nối PostgreSQL ở namespace `database`** — nguyên nhân này nằm
  ngoài đồ thị (giới hạn ở mục 4), chỉ AI thấy qua log.
- **Webhook đầu-cuối:** lỗi image trong `rca-lab` → Alertmanager trên lab1 tự gọi webhook → diagnosis
  "From alert" xếp đúng `Rollout` hạng 1.

### 2.4 Lỗi tìm ra nhờ kiểm thử (đã sửa)

| Lỗi | Phát hiện ở | Sửa |
|---|---|---|
| Image sai khi rolling update không có "triệu chứng" (pod cũ vẫn chạy) | thiết kế kịch bản | trạng thái pod critical cũng là triệu chứng |
| Rollout tăng request không nối được tới Unschedulable | kịch bản too-big | thêm luật `rollout-unschedulable` |
| Hai alert cùng một sự cố → hai diagnosis | webhook thật | chống trùng theo đối tượng 10 phút + lock |
| Groq: báo cáo gửi dưới dạng gọi tool `json` (400) | run từ alert | lấy lại từ `failed_generation`, hỏi lại không kèm tool |
| Groq: suy nghĩ dở thay cho lời gọi tool (400 `output_parse_failed`) | đánh giá | cùng đường hỏi lại không kèm tool |
| Deployment mới tạo bị coi là "ScaleChange" | kịch bản pvc-pending | ReplicaSet đầu tiên tính là "mới sinh" |
| Events Loki dạng logfmt có ngoặc kép bị parse sai | Alloy thật | parser logfmt đúng chuẩn |
| Báo cáo mô tả "ảnh hưởng" khi không có sự cố | namespace khoẻ | cảnh báo "không có triệu chứng" + luật trong lời nhắc |

## 3. So sánh với các framework và giải pháp hiện có

| Giải pháp | Cách làm | Mạnh | Yếu so với nhu cầu của K8s-Hub |
|---|---|---|---|
| **Groot** (eBay, ASE'21) | Đồ thị sự kiện + luật + PageRank | 952 sự cố thật, top-1 78%, top-3 95%, < 5 s; minh bạch | Dữ liệu và luật không công bố; dựa vào trace dày đặc của eBay |
| **k8sgpt** (CNCF) | Analyzer theo loại tài nguyên, LLM giải thích từng finding (tuỳ chọn) | Nhẹ, nhanh, phủ nhiều loại tài nguyên | Không nhân quả, không thời gian, không thay đổi, không xếp hạng (đo ở 2.1: 6/8, trượt 2 ca do thay đổi) |
| **HolmesGPT** (Robusta), **kubectl-ai** (Google) | Agent LLM gọi tool (kubectl, Prometheus, Loki…) theo vòng lặp | Linh hoạt, tự đi tìm; HolmesGPT có runbook | Tốn token, chậm, phụ thuộc hoàn toàn vào LLM; kết quả khó tái lập (đo kiến trúc này ở 2.2) |
| **Phương pháp học thuật cho microservice** (bộ RCAEval: BARO, CIRCA, RCD, MicroCause…) | Thống kê/nhân quả trên metric và trace | Định vị service/metric gốc trên telemetry dày | Cần telemetry dày; không dùng trạng thái và lịch sử thay đổi của Kubernetes |
| **LLM đọc telemetry thô** (OpenRCA, ICLR'25) | Đưa log/metric/trace thô cho LLM | Không cần thiết kế luật | Chính bài báo đo được độ chính xác rất thấp (~5–11%) — lý do K8s-Hub nén thành sự kiện |
| **Thương mại** (Dynatrace Davis, Datadog Watchdog RCA…) | Topology + sự kiện + nhân quả trên dữ liệu APM | Sản phẩm hoàn chỉnh | Đóng, cần agent APM của hãng; không kiểm chứng được |

**K8s-Hub đứng ở đâu:** lấy khung Groot (nhân quả có luật, minh bạch), thay nguồn dữ liệu bằng thứ cụm nhỏ
nào cũng có (trạng thái + events + thay đổi của Kubernetes, kể cả thay đổi qua chính K8s-Hub), và chỉ dùng
LLM ở bước cuối có ngân sách — rẻ và bền hơn agent thuần LLM, giải thích được hơn k8sgpt. Điểm khác biệt
riêng: **sự kiện "thay đổi đã duyệt qua K8s-Hub"** nối thẳng nhật ký phê duyệt vào đồ thị nhân quả.

## 4. Hạn chế và mối đe doạ tới tính hợp lệ

- **Bộ kịch bản nhỏ và dễ**: 8 lỗi đơn, mỗi lần một lỗi, namespace sạch, nhãn do tác giả đặt; luật được
  viết cùng lúc với kịch bản (rủi ro "học thuộc đề"). Chưa có lỗi chồng lỗi, lỗi mạng, lỗi phụ thuộc
  chéo service.
- **Phần LLM chỉ là mẫu nhỏ** do hạn mức miễn phí; hai lần chạy LLM chồng thời gian nhau.
- **Nguyên nhân ngoài namespace** không có trong đồ thị (ca Langfuse → database).
- **Đồ thị gọi giữa service** còn thưa (trace ít) — chủ yếu dựa vào chú thích `k8s-hub.io/depends-on`.
- **ConfigMap mới tạo** cũng tính là thay đổi (ca missing-key xếp nó hạng 2, chưa sai nhưng nhiễu).
- **Vận hành:** chạy trong tiến trình backend (chưa có worker), webhook trỏ IP máy dev, trạng thái bộ quét
  nằm trong bộ nhớ.

## 5. Hướng cải thiện (xếp theo giá trị / công sức)

> **Cập nhật 08/10/2026:** hướng 1–5 **đã làm** (chi tiết `docs/ke-hoach/rca-cai-tien.md`,
> `docs/hien-trang-codebase.md` mục 3.12); 6–8 người dùng chọn bỏ qua. Đánh giá lại sau thay đổi: vẫn
> top-1 8/8 (`rca_eval/results/20261008-073724.md`).

1. **Mở rộng phạm vi chéo namespace** (đúng bài học Groot: mở rộng đồ thị theo phụ thuộc). Đọc tên Service
   trong env/ConfigMap (`pg-rw.database.svc…`) → thêm Service/Workload ở namespace khác vào topology và
   snapshot. Giải quyết đúng ca Langfuse → database.
2. **Đồ thị gọi thật**: metric service-graph của Beyla (đã bật trong Alloy) hoặc service graph của Tempo
   (metrics-generator) → cạnh `callee` không cần chú thích tay.
3. **Thêm nguồn "thay đổi"**: lịch sử sync của Argo CD, revision của Helm (chỉ metadata), ControllerRevision
   của StatefulSet/DaemonSet, thay đổi Secret qua `managedFields` (chỉ metadata, không đọc giá trị); phân
   biệt "tạo mới" với "sửa" (prior thấp hơn cho tạo mới).
4. **Học trọng số luật từ phản hồi** (bước Groot hoãn lại): nút "đúng/sai nguyên nhân" trên trang chi tiết
   + verdict của AI → tinh chỉnh trọng số luật và prior (hồi quy logistic đơn giản), đo lại bằng `rca_eval`.
5. **Phát hiện bất thường tốt hơn**: change-point Bayesian trực tuyến kiểu BARO cho metric, tính mùa vụ;
   so mẫu log Drain3 với cửa sổ nền dài hơn.
6. **Bộ đánh giá lớn hơn và công bằng hơn**: thêm lỗi bằng Chaos Mesh (độ trễ/mất gói, CPU stress, DNS,
   kill pod, lỗi chồng lỗi), lặp mỗi kịch bản nhiều lần, chỉ số AC@k/Avg@k/MRR như RCAEval; chạy **chính
   HolmesGPT và kubectl-ai** trên cùng kịch bản; chạy phần LLM với khoá trả phí để đủ mẫu.
7. **Độ tin cậy của bước LLM**: dùng chế độ structured output (JSON schema) của nhà cung cấp thay vì
   parse văn bản — loại hẳn nhóm lỗi Groq 400 ở 2.4.
8. **Vận hành**: hàng đợi worker (Redis đã có trong cấu hình), lưu trạng thái bộ quét vào CSDL, bầu leader
   khi nhiều replica, webhook trỏ Service trong cụm khi backend chạy thành pod.

## 6. Chạy lại

```bash
cd backend
# Phần tất định + k8sgpt (không tốn LLM):
KUBECONFIG=~/.kube/lab1.yaml PYTHONUTF8=1 .venv/Scripts/python.exe -u -m rca_eval.run \
    --no-report --no-baseline --k8sgpt <đường dẫn k8sgpt.exe>
# Đủ cả báo cáo AI + agent LLM (cần quota; Gemini miễn phí thì thêm --rpm 4):
KUBECONFIG=~/.kube/lab1.yaml PYTHONUTF8=1 .venv/Scripts/python.exe -u -m rca_eval.run \
    --provider google --model gemini-2.5-flash --rpm 4 --k8sgpt <đường dẫn k8sgpt.exe>
```
Ghi vào cụm (namespace `rca-lab`) và tạo một dòng `approvals` mỗi lần chạy kịch bản scale-zero.
