"""Root Cause Analysis endpoints.

TODO:
  POST /rca/runs                  - kick off phien RCA (target: namespace/workload/alert)
  GET  /rca/runs                  - lich su
  GET  /rca/runs/{id}             - report: timeline + evidence + hypotheses
  GET  /rca/runs/{id}/stream      - SSE tien trinh phan tich
"""

from fastapi import APIRouter

router = APIRouter()
