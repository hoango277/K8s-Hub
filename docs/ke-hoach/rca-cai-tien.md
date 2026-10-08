# Kế hoạch: cải tiến RCA (sau đánh giá 07/10/2026)

*Người dùng chọn ngày 07/10/2026 từ mục 5 của `docs/rca-tong-ket.md`: làm hướng 1–5, bỏ 6–8. Đây là
**kế hoạch**; những gì chạy thật ghi ở `docs/hien-trang-codebase.md` mục 3.12.*

## Tiến độ

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| 1. RCA toàn cụm (chéo namespace) | **Xong** (08/10/2026) | Snapshot cả cụm; phạm vi = namespace + phụ thuộc 2 bước, mở rộng thêm một vòng khi log/trace lộ phụ thuộc mới; chẩn đoán cả cụm (`namespace="*"`); 47 luật lan lỗi qua phụ thuộc. Chạy thật: `langfuse` tự kéo `database` vào |
| 2. Đồ thị gọi từ mọi nguồn | **Xong** | config, metric (Beyla `http_client_*`/`db_client_*`, khớp tiền tố khi duy nhất), trace, log, annotation; mỗi cạnh ghi nguồn. lab1: 31 cạnh, `langfuse-worker → clickhouse` có cả config + metric |
| 3. Thêm nguồn thay đổi | **Xong** | ControllerRevision, Argo CD, Helm (metadata Secret), SecretChange (metadata), tạo mới ×0,4 |
| 4. Học trọng số từ phản hồi | **Xong** | Nút Right cause / Not it (engineer+), bảng `rca_weights`, hệ số kẹp [0,5; 1,5], `rca_eval --feedback`. Chưa có dữ liệu phản hồi thật |
| 5. Phát hiện bất thường tốt hơn | **Xong** | change-point, so với hôm qua, MemoryLeak, nền log 6 giờ |

## Dữ liệu có sẵn trên lab1 (kiểm ngày 07/10/2026, chỉ đọc)

- Env của workload chứa địa chỉ dịch vụ khác namespace: `langfuse-worker` → `DATABASE_HOST=pg-rw.database.svc.cluster.local`,
  cùng namespace thì tên ngắn (`langfuse-redis`, `langfuse-clickhouse-headless:8123`).
- Beyla xuất metric **phía client**: `http_client_request_duration_seconds_*` và
  `db_client_operation_duration_seconds_*` với nhãn bên gọi (`k8s_namespace_name`, `k8s_deployment_name`)
  và bên được gọi (`server_address`, `server_port`). **Không có** `traces_service_graph_*`.
- Argo CD: 5 `Application` (cert-manager, clickhouse-operator, cnpg, langfuse, tempo).
- Helm: release lưu ở Secret `sh.helm.release.v1.<tên>.v<số>` (nhãn `owner=helm`, `name`, `version`, `status`).
- 18 `ControllerRevision` (lịch sử StatefulSet/DaemonSet).

## 1. RCA toàn cụm

- **Snapshot cả cụm** (mỗi loại một lời gọi `list` cho mọi namespace — rẻ hơn gọi từng namespace), giữ
  namespace của từng đối tượng; topology dựng cho cả cụm.
- **Phạm vi phân tích** = namespace đang chẩn đoán **+ namespace của các dịch vụ nó phụ thuộc** (đi theo
  cạnh "gọi" tối đa 2 bước — đúng cách Groot mở rộng đồ thị phụ thuộc quanh dịch vụ bị cảnh báo). Detector
  telemetry hỏi một lần cho cả phạm vi (`namespace=~"a|b"`).
- **Chẩn đoán cả cụm**: không chọn namespace = mọi namespace được phép; dùng cho bộ quét và nút "Whole
  cluster" trên giao diện. Lưu `namespace="*"` trong `rca_runs`.
- `K8S_ALLOWED_NAMESPACES` vẫn áp: phạm vi luôn giao với danh sách cho phép.
- **Luật chéo dịch vụ**: quan hệ ghép (`owner+callee+pods`…) để nối lỗi ở pod bên được gọi (database
  crash, không sẵn sàng, mất endpoint) tới triệu chứng ở bên gọi (crash, log lỗi, probe lỗi, lỗi request).

## 2. Đồ thị gọi từ mọi nguồn

Mỗi cạnh "A gọi B" ghi lại **nguồn** để hiện trên giao diện:

| Nguồn | Cách lấy |
|---|---|
| config | Tên host trong env (giá trị thường, không đọc Secret) và dữ liệu ConfigMap: `svc`, `svc.ns`, `svc.ns.svc[.cluster.local]`, URL `scheme://host:port` → Service → workload phía sau |
| metric | Beyla `http_client_*`, `db_client_*`: (namespace, deployment) gọi `server_address` |
| trace | Tempo: span cha/con khác service, dùng `k8s.namespace.name` của từng span (chéo namespace) |
| log | Tên host trong dòng log lỗi của pod đang lỗi ("connection refused to pg-rw.database…:5432") |
| annotation | `k8s-hub.io/depends-on` (giữ, cho phép `ns/name`) |

## 3. Thêm nguồn thay đổi

- **StatefulSet/DaemonSet rollout** qua `ControllerRevision` (diff image/env/resources như Deployment).
- **Argo CD sync**: `Application.status.history[].deployedAt` trong cửa sổ → sự kiện `GitOpsSync` trên các
  workload/ConfigMap mà Application quản lý (`status.resources`).
- **Helm upgrade**: Secret release của Helm chỉ đọc **metadata** (yêu cầu `PartialObjectMetadataList` —
  server không trả `data`, giá trị không bao giờ tới backend) → sự kiện `HelmRelease` trên workload có
  annotation `meta.helm.sh/release-name`.
- **Secret thay đổi**: cũng chỉ metadata (`managedFields`) → `SecretChange` trên Secret mà pod tham chiếu.
- **Tạo mới ≠ sửa**: ConfigMap/Secret mới tạo có trọng số "khả năng là gốc" thấp hơn (giảm nhiễu như ca
  missing-key).

## 4. Học trọng số từ phản hồi

- Trang chi tiết: engineer/admin bấm **"Đúng nguyên nhân / Không phải"** trên từng nguyên nhân → lưu vào
  `rca_hypotheses` (`feedback`, người, thời điểm).
- Bảng `rca_weights` (khoá `rule:<id>` hoặc `type:<loại>`, số lần đúng/sai, hệ số): đúng → tăng trọng số
  loại sự kiện gốc và các luật trong chuỗi; sai → giảm. Hệ số làm trơn kiểu Bayes, kẹp trong [0,5; 1,5]
  để vài phản hồi không lật được cả hệ.
- Áp hệ số khi phân tích (trọng số luật × hệ số, prior × hệ số). `rca_eval --feedback` ghi nhãn đúng của
  kịch bản làm phản hồi (nguồn `eval`).
- Không dùng verdict của AI làm phản hồi (AI có thể sai).

## 5. Phát hiện bất thường tốt hơn

- **Change-point** thay cho "30% đầu cửa sổ làm nền": tìm điểm chia làm hai đoạn khác nhau nhất (hiệu
  trung vị chuẩn hoá bằng MAD) → biết đúng thời điểm thay đổi, bền với nhiễu.
- **Mùa vụ** cho tỉ lệ lỗi/độ trễ: so với cùng giờ hôm qua (`offset 1d`); hôm qua cũng vậy thì không báo.
- **Rò rỉ bộ nhớ**: xu hướng tăng đều, dự báo chạm limit trong cửa sổ ngắn → `MemoryLeak` (tài nguyên).
- **Mẫu log mới** so với nền dài hơn (6 giờ trước cửa sổ) thay vì đầu cửa sổ.

## Kiểm tra

- Unit test cho từng phần: parse hostname, topology chéo namespace, luật chéo dịch vụ, ControllerRevision,
  Argo CD, Helm metadata, trọng số học, change-point, mùa vụ.
- Chạy thật chỉ đọc: chẩn đoán `langfuse` phải kéo được `database` vào phạm vi; chẩn đoán cả cụm.
- Chạy lại `rca_eval` phần tất định: không được tụt dưới 8/8.
