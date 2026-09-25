"""Observability of the system itself (Langfuse) + cluster metrics.

TODO:
  GET /observability/traces               - proxy the trace list from Langfuse
  GET /observability/traces/{id}          - trace details for one message
  GET /observability/metrics/usage        - token / cost / latency
  GET /observability/metrics/cluster      - proxy Prometheus queries
"""

from fastapi import APIRouter

router = APIRouter()
