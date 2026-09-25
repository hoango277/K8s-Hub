"""Self-monitoring: watch the health of the K8s-Hub app itself.

Entirely different from the following two, even though they share tooling:
  - app/integrations/prometheus, app/integrations/loki
      -> READ the target K8s cluster, as evidence for RCA
  - app/modules/observability
      -> monitor the LLM/agent (Langfuse)

This module WRITES this backend's own metrics/logs for Prometheus to scrape
and for Loki to collect.

TODO:
  - expose /metrics (prometheus-fastapi-instrumentator)
  - custom metrics: request latency, open SSE connections,
    runbook queue length, number of K8s API calls, error rate
  - structlog -> JSON stdout so Promtail/Alloy can ship it to Loki
  - RED metrics per endpoint
"""
