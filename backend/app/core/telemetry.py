"""Self-monitoring: giam sat suc khoe cua chinh app K8s-Hub.

Khac hoan toan voi 2 thu sau du dung chung cong cu:
  - app/integrations/prometheus, app/integrations/loki
      -> DOC cum K8s dich, lam evidence cho RCA
  - app/modules/observability
      -> giam sat LLM/agent (Langfuse)

O day la GHI metrics/logs cua chinh backend nay ra cho Prometheus scrape
va cho Loki thu thap.

TODO:
  - expose /metrics (prometheus-fastapi-instrumentator)
  - custom metrics: request latency, SSE connection dang mo,
    do dai queue runbook, so K8s API call, error rate
  - structlog -> JSON stdout de Promtail/Alloy day sang Loki
  - RED metrics cho tung endpoint
"""
