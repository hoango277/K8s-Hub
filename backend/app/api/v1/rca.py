"""Root Cause Analysis endpoints.

TODO:
  POST /rca/runs                  - kick off an RCA run (target: namespace/workload/alert)
  GET  /rca/runs                  - history
  GET  /rca/runs/{id}             - report: timeline + evidence + hypotheses
  GET  /rca/runs/{id}/stream      - SSE analysis progress
"""

from fastapi import APIRouter

router = APIRouter()
