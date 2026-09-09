"""Observability cua chinh he thong (Langfuse) + metrics cum.

TODO:
  GET /observability/traces               - proxy list trace tu Langfuse
  GET /observability/traces/{id}          - chi tiet trace cua 1 message
  GET /observability/metrics/usage        - token / cost / latency
  GET /observability/metrics/cluster      - proxy query Prometheus
"""

from fastapi import APIRouter

router = APIRouter()
