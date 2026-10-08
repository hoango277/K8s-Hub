# Kế hoạch: RCA kiểu Groot (event graph) cho K8s-Hub

*Kế hoạch đã được người dùng duyệt ngày 07/10/2026. Đây là **kế hoạch**: những gì đã chạy thật được
ghi ở `docs/hien-trang-codebase.md` (mục 3.12). Cập nhật bảng "Tiến độ" ngay dưới mỗi khi xong một
giai đoạn.*

## Tiến độ

| Giai đoạn | Trạng thái | Ghi chú |
|---|---|---|
| 0. Hạ tầng | **Xong** (07/10/2026) | Alloy hết crash-loop; events vào Loki với `job="kubernetes-events"`. Namespace `rca-lab` + PrometheusRule nhanh + AlertmanagerConfig đã apply (`deploy/rca-lab/base.yaml`); firewall máy dev mở TCP 8000 cho lab1 |
| 1. Nền dữ liệu + detector | **Xong** (07/10/2026) | `model`, `snapshot`, `topology`, `events_store`, 7 detector, 14 test, chạy thử trên lab1 |
| 2. Lõi Groot | **Xong** (07/10/2026) | 65 luật, `causality`, `ranking`, `pipeline`, bảng `rca_runs`/`rca_hypotheses` (migration `b81f0c2d4e57`, đã áp), API, tool chat `diagnose_incident`. Thêm `GET /rca/targets*` cho form |
| 3. LLM kiểm chứng + khắc phục | **Xong** (07/10/2026) | `report.py` (ngân sách tool, validator), `remediation.py` (AI chỉ chọn id ứng viên; đề xuất qua approvals với vai trò `user`). Chạy thật trên `langfuse` |
| 4. Frontend | **Xong** (07/10/2026) | `/rca`, `/rca/[runId]`: báo cáo, top-3 + chuỗi, đồ thị SVG, dòng thời gian, đề xuất sửa. Khác kế hoạch: tiến trình đọc bằng polling run (bước lưu trong CSDL), endpoint SSE vẫn có cho client khác |
| 5. Trigger | **Xong** (07/10/2026) | `POST /rca/alerts` (bearer token, chống trùng theo fingerprint 60 phút, gộp theo đối tượng), `scanner.py` (`RCA_SCAN_INTERVAL_MINUTES` + `RCA_SCAN_NAMESPACES`, mỗi triệu chứng chỉ chẩn đoán một lần). Đã chạy thật: Alertmanager trên lab1 gọi webhook khi `web` bị đổi sang image sai, run xếp `Rollout` đứng đầu. Thêm chống trùng theo đối tượng (10 phút) sau khi thấy 2 alert cùng giây tạo 2 run |
| 6. Đánh giá | **Xong** (07/10/2026) | `backend/rca_eval/` 8 kịch bản + so với k8sgpt và agent LLM. Phần tất định top-1 8/8 (k8sgpt 6/8); phần LLM mẫu nhỏ do hết quota miễn phí. Tổng kết, hạn chế và hướng cải thiện: `docs/rca-tong-ket.md` |

## Bối cảnh

Trước đây phần Diagnosis (RCA) chỉ là khung: `modules/rca/*` toàn file một dòng `TODO`, trang `/rca`
là ComingSoon. Người dùng muốn RCA **không nhồi log/metric thô vào LLM** (OpenRCA, ICLR'25: LLM đọc
telemetry thô chỉ đúng khoảng 5–11%) và chọn hướng **Groot (eBay, ASE'21)**.

Quyết định đã chốt với người dùng:
- Lưu lịch sử Kubernetes events: **Loki qua Alloy** (Kubernetes chỉ giữ events 1 giờ). Xem lý do và
  phương án thay thế ở mục 6.
- Kích hoạt: **nút trên trang Diagnosis, tool trong chat, webhook Alertmanager, quét định kỳ**.
- LLM: **viết báo cáo + kiểm chứng giả thuyết** bằng một số lời gọi tool đọc có giới hạn.
- Có **đánh giá top-k** bằng kịch bản gây lỗi có nhãn trên lab1.
- Được phép **bỏ khung cũ, xây lại** (đã làm).

Kết quả mong muốn:
- Một lần RCA cho ra top-3 nguyên nhân, mỗi cái kèm chuỗi nhân quả và bằng chứng trích dẫn.
- Phần tất định chạy trong vài giây; phần LLM có ngân sách token cố định.
- Đề xuất khắc phục đi qua luồng phê duyệt có sẵn.
- Có số liệu top-1/top-3 cho đồ án.

### Nghiên cứu nền (tóm tắt)

| Hướng | Ý chính | Dùng cho K8s-Hub |
|---|---|---|
| Groot (eBay, ASE'21) | Đồ thị sự kiện + luật + PageRank. 952 sự cố thật, top-1 78%, top-3 95%, < 5 s | **Hướng chính** |
| OpenRCA (ICLR'25) | LLM đọc telemetry thô chỉ đúng 5–11% | Lý do không nhồi dữ liệu thô vào LLM |
| EviRCA | Tách bước trích bằng chứng khỏi bước suy luận | LLM chỉ nhận bằng chứng đã nén |
| SynergyRCA | Đồ thị trạng thái/meta trên Neo4j | Ý tưởng đồ thị thực thể; không cần Neo4j vì đồ thị nhỏ |
| HolmesGPT, k8sgpt | Quản lý ngữ cảnh; analyzer theo loại tài nguyên | Ý tưởng cho detector |

## 1. Cơ chế RCA của Groot

Nguồn: bài ASE'21 "Groot: An Event-graph-based Approach for RCA in Industrial Settings" và blog kỹ thuật
của eBay. Groot là **knowledge engineering + đồ thị**, không phải mô hình học máy. Ba bước:

1. **Service Dependency Graph (SDG)**: service nào phụ thuộc service nào. Đồ thị dựng **động** quanh
   các service có cảnh báo, không dựng toàn bộ hệ thống mỗi lần.
2. **Event Causality Graph (ECG)**: **nút là SỰ KIỆN**, không phải service. Sự kiện có ba nhóm: metric
   bất thường (latency tăng, timeout); trạng thái/log (CPU cao, GC cao); **hoạt động của con người**
   (deploy, đổi config). Cách dựng:
   - Bắt đầu từ sự kiện triệu chứng ở service bị cảnh báo, rồi mở rộng dần theo SDG.
   - Hai sự kiện chỉ được nối khi có **luật**. Có ba loại luật: cùng service, theo phụ thuộc, và có
     điều kiện/động (theo ngữ cảnh, ví dụ cùng datacenter).
   - Luật viết bằng một ngữ pháp nhỏ để SRE bổ sung tri thức.
   - Cặp sự kiện không có luật thì **không** được nối, dù hai service phụ thuộc nhau. Đây là điểm khác
     cách "Naive Dependency".
3. **Xếp hạng nguyên nhân**: kiểu PageRank trên ECG, trọng số theo loại sự kiện do SRE đặt. **Công
   thức và trọng số cụ thể không được công bố**; K8s-Hub tự thiết kế (mục 3.5) và ghi rõ đó là thiết kế
   riêng.

Kết quả eBay công bố: 952 sự cố thật, top-1 78%, top-3 95%, dưới 5 giây. Groot vượt cả "Naive
Dependency" (không có nút sự kiện) lẫn "Non-adaptive Event" (không có luật điều kiện).

**Các điểm lưu ý khi áp vào K8s-Hub:**
- Chất lượng nằm ở **bộ phát hiện sự kiện và bộ luật**, không nằm ở thuật toán xếp hạng.
- Phải có sự kiện **thay đổi do con người**: rollout, đổi image, đổi config, scale, thay đổi qua
  approval. Phần lớn sự cố Kubernetes bắt nguồn từ thay đổi.
- **Minh bạch** là điều kiện để người vận hành tin kết quả: UI hiện đồ thị, mỗi cạnh ghi luật nào tạo
  ra nó, mỗi nút có bằng chứng thô.
- eBay **hoãn ML** tới khi hệ luật ổn định. K8s-Hub cũng vậy: chỉ dùng thống kê nhẹ (bất thường
  metric) và gom log thành mẫu (Drain3); không huấn luyện mô hình.
- Đánh giá bằng **top-k accuracy** trên bộ sự cố có nhãn.
- Khác biệt về quy mô: eBay có khoảng 5.000 service, K8s-Hub khoảng 30 workload.
- Khác biệt về nguồn SDG: eBay có trace dày đặc, lab1 thì không (mục 2), nên cạnh phụ thuộc của
  K8s-Hub chủ yếu lấy từ **cấu trúc Kubernetes**.

## 2. K8s-Hub có gì / thiếu gì (kiểm ngày 07/10/2026)

**Dùng lại được:**
- `integrations/k8s/resources.py`: `resolve_kind`, `list_objects`, `get_object`. `clean()` bỏ
  annotation `deployment.kubernetes.io/revision`, nên RCA đọc object thô.
- `integrations/prometheus|loki|tempo/client.py`.
- Luồng phê duyệt `services/approval_service.propose(plan, actor=…, source=…)` và các hàm
  `nl_command/planner.plan_*`.
- Langfuse `trace_attributes`; LLM qua `integrations/llm/client.get_llm`.
- Hợp đồng SSE: `StepEvent` đã có nhưng chưa được phát ra.

**Thiếu / không phù hợp (trạng thái hiện tại):**
- ~~Client chỉ hỏi được "N phút tới hiện tại"~~ → **đã thêm** `end`/`at` tuyệt đối.
- Không có lịch sử Kubernetes events: TTL 1 giờ, và Alloy chưa chạy `loki.source.kubernetes_events`
  (mục 6).
- ~~Alloy crash-loop~~ → **đã hết**, nhưng cấu hình đang chạy chưa có nguồn events.
- Đồ thị service gọi service còn thưa:
  - Hubble không xuất metric;
  - Beyla có metric `http_server_*` nhưng ít mẫu;
  - Tempo mới có trace mẫu.

  Cạnh "gọi" lấy từ trace hoặc chú thích `k8s-hub.io/depends-on`.
- ~~`rca_report.py` + migration `e6f1a9b47c20` tạo nhánh Alembic thứ hai~~ → **đã xoá**.
- Không có hàng đợi/worker. Quét định kỳ dùng một vòng asyncio trong lifespan (chạy được một bản duy
  nhất).
- ~~Thiếu `drain3`~~ → **đã thêm**.

## 3. Thiết kế

### 3.1 Mô hình dữ liệu — `modules/rca/model.py` (xong)
- `Entity(kind, namespace, name, sub)`.
- `Event(id, type, entity, start, end, severity, attrs, evidence[])`.
- `Evidence` ≤ 300 ký tự.
- `CausalEdge(cause, effect, rule, weight, why)`.
- `Hypothesis`.
- `EVENT_TYPES`: 29 loại sự kiện kèm trọng số "khả năng là gốc".

### 3.2 SDG = đồ thị thực thể — `modules/rca/topology.py` (xong)
Các cạnh:
- owner (Workload ← Pod)
- node
- config / volume (Pod → ConfigMap/Secret/PVC)
- backends / backend_workloads (Service)
- routes (Ingress)
- hpa
- callee / caller: từ chú thích `k8s-hub.io/depends-on` hoặc từ trace

`ensure_pod` nối pod đã bị xoá về workload của nó qua tên pod.

### 3.3 Phát hiện sự kiện — `modules/rca/detectors/*` (xong)

| Detector | Loại sự kiện | Nguồn |
|---|---|---|
| `pods.py` | CrashLoop, OOMKilled, ImagePullError, ContainerConfigError, ProbeFailed, PodNotReady, Evicted, Unschedulable, VolumeMountFailed, RestartSpike | trạng thái pod + events |
| `nodes.py` | NodeNotReady, NodePressure, NodeCordon, NodeSaturated | Node conditions + Prometheus |
| `workloads.py` | ReplicasUnavailable, RolloutStuck, ServiceNoEndpoints, PvcPending, HpaAtMax | Deployment/StatefulSet/DaemonSet/Service/PVC/HPA |
| `changes.py` | Rollout (diff image/env/resources với RS trước), ScaleChange, ConfigChange, ApprovalExecuted | API + `approvals` + events |
| `metrics.py` | MemoryNearLimit, CpuThrottling, ErrorRateSpike, LatencySpike | Prometheus (cAdvisor, kube-state-metrics, Beyla) |
| `logs.py` | LogErrorSpike + mẫu log mới (Drain3) | Loki |
| `traces.py` | DownstreamErrors + cạnh "gọi" | Tempo |
| `events_store.py` | (nguồn) Kubernetes events: API ≤ 1 giờ + Loki | API + Loki |

### 3.4 Luật nhân quả + ECG — `rules.py`, `causality.py` (giai đoạn 2)

**Luật là dữ liệu.** Mỗi luật gồm:
- `id`, `cause_type`, `effect_type`;
- `relation`: một quan hệ trong `topology.RELATIONS`, tính từ thực thể của KẾT QUẢ tới nơi có thể có
  NGUYÊN NHÂN;
- `max_lag` và slack: nguyên nhân phải xảy ra trước kết quả;
- `condition` (tuỳ chọn);
- `weight` (0..1);
- `why` (câu giải thích hiện trên UI).

Khoảng 30 luật. Ví dụ:
- `Rollout(image đổi) -pods→ ImagePullError`
- `Rollout -pods→ CrashLoop` (trong 30 phút)
- `ConfigChange -used_by→ CrashLoop / ContainerConfigError`
- `MemoryNearLimit -same→ OOMKilled -same→ CrashLoop`
- `MemoryNearLimit -same→ CrashLoop` khi exit code 137
- `NodePressure -node_pods→ Evicted`
- `ProbeFailed -same→ PodNotReady -services→ ServiceNoEndpoints -caller→ ErrorRateSpike`
- `DownstreamErrors -caller→ ErrorRateSpike`
- `ScaleChange(0) -backed_by→ ServiceNoEndpoints`
- `PvcPending -mounted_by→ Unschedulable`
- `NodeSaturated → Unschedulable` (luật có điều kiện, đọc "Insufficient cpu" trong message)

**Sự kiện bắt đầu trước cửa sổ** (start bị kẹp về đầu cửa sổ, ví dụ crash-loop đã kéo dài nhiều ngày)
thì không biết được thứ tự thời gian thật. Luật được bỏ qua điều kiện "nguyên nhân trước kết quả" khi
kết quả là sự kiện "đang diễn ra từ trước", nhưng giảm trọng số cạnh.

**Dựng ECG:**
1. Lấy các sự kiện triệu chứng ở thực thể đích (hoặc mọi triệu chứng trong namespace).
2. BFS **ngược** theo luật, độ sâu tối đa 5, tối đa 200 nút.
3. Không có luật thì không có cạnh.

### 3.5 Xếp hạng — `ranking.py` (thiết kế riêng)
- **Personalized PageRank** trên ECG đảo chiều (cạnh từ kết quả → nguyên nhân):
  - vector khởi động đặt ở các sự kiện triệu chứng;
  - trọng số cạnh = `weight` của luật × hệ số gần nhau về thời gian;
  - damping 0,85, lặp tới khi hội tụ. Tự viết, không cần networkx.
- `score = PPR × prior(loại sự kiện)`, cộng thưởng cho nút gốc (không còn nguyên nhân phía trước).
- Hoà điểm thì sự kiện **sớm hơn** thắng.
- Đầu ra là top-k (mặc định 3), mỗi mục kèm chuỗi nhân quả và bằng chứng.

### 3.6 LLM: kiểm chứng + báo cáo — `report.py` (giai đoạn 3)
- **Đầu vào cố định:** top-3, chuỗi nhân quả, bằng chứng, dòng thời gian ≤ 30 sự kiện; tổng khoảng
  ≤ 6.000 token. Không bao giờ đưa log hay metric thô.
- **Kiểm chứng:** tối đa `RCA_LLM_TOOL_BUDGET` (mặc định 4) lời gọi tool **chỉ đọc** có sẵn. Hết ngân
  sách thì buộc viết báo cáo.
- **Đầu ra JSON có schema:** `{summary, root_cause_rank, verdicts[{rank, status, evidence_ids}],
  remediation?, explanation}`.
- **Validator tất định:** `evidence_ids` phải có thật; remediation phải map được sang một hàm
  `planner.plan_*` hợp lệ.
- Lỗi LLM hoặc hết quota thì vẫn trả kết quả tất định.
- Ghi Langfuse qua `trace_attributes`.

### 3.7 Khắc phục qua phê duyệt — `remediation.py` (giai đoạn 3)
- Map loại nguyên nhân sang đề xuất:
  - Rollout xấu → `plan_set_image` về image cũ;
  - OOM → gợi ý tăng limit (`plan_apply`);
  - Scale về 0 → `plan_scale`.
- Gọi qua `approval_service.propose`. Trigger alert/scan dùng actor `rca@k8s-hub` với vai trò `user`,
  để **không bao giờ tự chạy**.

### 3.8 Lưu trữ + API (giai đoạn 2)

**Bảng** (migration nối sau `9d4b6e1f2a73`):
- `rca_runs`: id, trigger (`manual|chat|alert|scan`), requested_by, target, window start/end, status,
  error, graph JSONB, timeline JSONB, report JSONB, llm_trace_id, approval_id, alert_fingerprint,
  started/finished.
- `rca_hypotheses`: rank, event_id, score, chain JSONB, verdict.

**API:**
- `POST /rca/runs`, `GET /rca/runs`, `GET /rca/runs/{id}`.
- `GET /rca/runs/{id}/stream`: SSE dùng `StepEvent`/`ErrorEvent`/`DoneEvent` có sẵn.
- `POST /rca/alerts`: webhook Alertmanager, xác thực bằng `ALERTMANAGER_WEBHOOK_TOKEN`, chống trùng
  theo fingerprint.

**Tool chat** `diagnose_incident(namespace, workload?, since_minutes)`.

**Config:** `RCA_LOOKBACK_MINUTES`, `RCA_SCAN_INTERVAL_MINUTES`, `RCA_LLM_TOOL_BUDGET`,
`ALERTMANAGER_WEBHOOK_TOKEN`.

**Prometheus:** chỉ đo sức khoẻ (số run theo trigger/kết quả, thời gian chạy).

### 3.9 Frontend (giai đoạn 4)
- **`/rca`:** danh sách run (đủ 4 trạng thái), dialog "New diagnosis".
- **`/rca/[runId]`:**
  - tiến trình trực tiếp;
  - dòng thời gian (thay đổi do con người được tô nổi);
  - đồ thị nhân quả SVG tự vẽ, mỗi cạnh ghi luật;
  - top-3 + verdict;
  - báo cáo;
  - thẻ phê duyệt.

### 3.10 Đánh giá — `backend/rca_eval/` + `deploy/rca-lab/` (giai đoạn 6)

Namespace `rca-lab`, request CPU rất nhỏ. 8 kịch bản:

| Kịch bản | Nhãn đúng |
|---|---|
| image tag sai sau rollout | Rollout |
| OOM | MemoryNearLimit/OOMKilled |
| ConfigMap sai | ConfigChange |
| thiếu key | ContainerConfigError |
| probe sai → mất endpoint | ProbeFailed |
| request vượt sức node | NodeSaturated/Unschedulable |
| PVC sai StorageClass | PvcPending |
| scale về 0 qua approval | ApprovalExecuted |

Tính top-1/top-3, thời gian, token; so với **baseline chỉ dùng LLM**. Áp kịch bản là ghi vào cụm, nên
chỉ chạy khi người dùng xác nhận.

## 4. Thứ tự làm

0. Hạ tầng: Alloy (events + Beyla), receiver webhook Alertmanager. Cần người dùng duyệt từng bước.
1. Nền dữ liệu (**xong**).
2. Lõi: `rules`, `causality`, `ranking`, `pipeline`, bảng + migration, API, tool chat.
3. LLM kiểm chứng + báo cáo + remediation.
4. Frontend.
5. Trigger: webhook + quét định kỳ.
6. Đánh giá + cập nhật tài liệu.

## 5. Kiểm tra

- **Unit test:**
  - detector với fixture;
  - luật/ECG: chỉ nối khi có luật, nguyên nhân phải xảy ra trước kết quả;
  - PageRank xếp đúng gốc;
  - pipeline với client giả;
  - validator loại `evidence_id` giả;
  - remediation map đúng hàm `plan_*`;
  - webhook: sai token bị từ chối, trùng fingerprint bị bỏ.
- `ruff`, `pytest`, `npm run typecheck`, `npm run lint` sạch.
- **Kiểm trực tiếp trên lab1** (ghi vào cụm thì phải xác nhận trước):
  - sự cố thật đang có;
  - từng kịch bản `rca-lab`;
  - Playwright ở 1440px và 390px;
  - alert giả bắn vào webhook.

## 6. Nguồn dữ liệu quan sát: RCA đọc gì, từ đâu

Hạ tầng lab1 có đủ ba loại tín hiệu, và **RCA đọc trực tiếp cả ba từ nơi lưu trữ** của chúng, không đi
qua Alloy:

| Tín hiệu | Nơi lưu (RCA đọc ở đây) | Ai thu thập | RCA dùng cho |
|---|---|---|---|
| Trạng thái cụm | Kubernetes API | — | snapshot, topology, mọi detector trạng thái |
| Metrics | Prometheus (kube-prometheus-stack) | Prometheus tự scrape: cAdvisor, kube-state-metrics, node-exporter. **Riêng metric HTTP của Beyla** được Alloy đẩy vào qua remote write | MemoryNearLimit, CpuThrottling, NodeSaturated; ErrorRate/Latency (Beyla) |
| Logs | Loki | Alloy (`loki.source.kubernetes`) đọc stdout mọi pod | LogErrorSpike + mẫu Drain3 |
| Traces | Tempo | app tự gửi OTLP, hoặc Beyla trong Alloy | cạnh "gọi", DownstreamErrors |
| Kubernetes events cũ hơn 1 giờ | Loki | Alloy (`loki.source.kubernetes_events`), **chưa bật** | `events_store` |
| Thay đổi qua K8s-Hub | Postgres (`approvals`) | K8s-Hub | ApprovalExecuted |

Alloy chỉ là **bộ thu gom/vận chuyển** (collector) cho log, events và tín hiệu Beyla. Nó không phải
nguồn RCA đọc. Đọc từ nơi lưu cũng có nghĩa là RCA không phụ thuộc collector nào: đổi Alloy sang
Promtail, Fluent Bit hay OTel Collector thì RCA không phải sửa, miễn dữ liệu vẫn vào Loki/Prometheus/Tempo.

**Vì sao events cần một thứ thu gom riêng:** Kubernetes events không phải metric, log hay trace.
- API server chỉ giữ events 1 giờ.
- Prometheus không lưu events (kube-state-metrics chỉ xuất trạng thái hiện tại).
- Muốn có lịch sử thì phải có thứ *watch* events và ghi đi nơi khác.

Các phương án:

| Phương án | Ưu | Nhược |
|---|---|---|
| **Alloy `loki.source.kubernetes_events`** (đã chọn) | Alloy đã có trên cụm; events nằm cạnh log trong Loki, Grafana xem chung | Phụ thuộc Alloy chạy ổn; DaemonSet nhiều node sẽ ghi trùng |
| `kubernetes-event-exporter` → Loki | Chuyên cho events, ổn định | Thêm một thành phần phải vận hành |
| K8s-Hub tự watch events, lưu Postgres | Không phụ thuộc hạ tầng quan sát | Chỉ có khi backend chạy liên tục; tự lo dọn dữ liệu cũ |

`events_store.py` đọc Loki theo label `job`, nên đổi sang `kubernetes-event-exporter` chỉ cần đổi
selector và bộ parse.
