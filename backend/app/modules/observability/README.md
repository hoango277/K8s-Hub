# Module: Observability (của LLM / Agent)

> **Phạm vi module này = giám sát chính con AI**, không phải giám sát cụm K8s.
>
> - Giám sát cụm K8s đích (nguồn evidence cho RCA) → `app/integrations/prometheus`, `app/integrations/loki`
> - Giám sát sức khỏe của chính app K8s-Hub → `app/core/telemetry.py`

Trả lời hai câu hỏi:

1. **LLM đã làm gì?** — prompt nào, model nào, gọi tool gì, tốn bao nhiêu token/tiền, mất bao lâu. → Langfuse.
2. **LLM đã tác động gì?** — resource nào thực sự bị thay đổi trên cluster, ai duyệt, diff ra sao, có phải rollback không. → audit log trong Postgres.

Langfuse **không** biết vế 2. Hai vế được nối với nhau bằng `trace_id`:

```
Langfuse trace ──trace_id──▶ audit_log (Postgres)
LLM định làm gì                thực tế đã đổi gì trên cluster
```

| File | Trách nhiệm |
|---|---|
| `langfuse_client.py` | Khởi tạo client + CallbackHandler cho LangGraph |
| `tracing.py` | Tạo trace/span, gắn `trace_id` vào message trả về cho FE |
| `prompts.py` | Đọc prompt có version từ Langfuse prompt management |
| `audit.py` | Ghi audit log append-only: actor, action, resource, diff, kết quả, `trace_id` |
| `impact.py` | Join trace ↔ audit: LLM đụng vào resource/namespace nào, blast radius |
| `evaluation.py` | Dataset + score: accuracy NL→command, chất lượng RCA (LLM-as-judge) |
| `metrics.py` | Chỉ số vận hành AI: approval rate, reject rate, dry-run fail rate, token/cost theo user |

## Chỉ số nên track (dùng cho chương đánh giá của luận văn)

**Chất lượng**
- Tỉ lệ plan sinh ra pass được dry-run (manifest hợp lệ)
- Tỉ lệ approve / reject / sửa tay của người vận hành
- Accuracy NL → intent + resource đích (chấm trên dataset cố định)
- RCA: tỉ lệ hypothesis hạng 1 trùng nguyên nhân thật

**Chi phí & hiệu năng**
- Token / cost mỗi request, mỗi phiên RCA
- Latency theo từng node của graph (tìm nút thắt)
- Số vòng tool call trung bình để hoàn thành 1 tác vụ

**An toàn**
- Số lần guardrail chặn (namespace ngoài phạm vi, danger op)
- Số action thực thi ở chế độ `auto` vs `require_approval`
- Số lần phải rollback sau khi apply
