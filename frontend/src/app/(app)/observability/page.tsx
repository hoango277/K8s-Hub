// USE CASE: Observability của LLM
//
// Trang này KHÔNG phải dashboard giám sát cụm K8s (cái đó thuộc RCA / Grafana).
// Nó trả lời: LLM đã làm gì, tốn bao nhiêu, và đã tác động gì lên cluster.
//
// TODO:
//   - Trace list (Langfuse): request → tool call → kết quả
//   - Token / cost / latency theo thời gian, theo user, theo use case
//   - Impact view: join trace ↔ audit log — resource/namespace nào bị đụng vào
//   - Chất lượng: approval rate, reject rate, dry-run fail rate
//   - Link "Mở trong Langfuse" theo trace_id

export default function ObservabilityPage() {
  return null;
}
