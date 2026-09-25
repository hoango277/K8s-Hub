"""AI observability endpoints — only what Langfuse cannot show.

Traces, token usage, cost and latency are NOT proxied here: the Langfuse UI
already shows them per turn, per user and per conversation, and the chat links
each answer straight to its trace. Rebuilding that screen would be a second
copy that can drift from the first.

TODO:
  GET /observability/impact/{trace_id}    - what that turn changed in the cluster (audit log)
  GET /observability/quality              - approval / rejection / failed dry-run rates
  GET /observability/metrics/cluster      - proxy Prometheus queries (target cluster)
"""

from fastapi import APIRouter

router = APIRouter()
