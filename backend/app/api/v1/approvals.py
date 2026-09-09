"""Human-in-the-loop approval gate.

TODO:
  GET  /approvals                 - hang doi cho duyet
  GET  /approvals/{id}            - chi tiet + diff / dry-run output
  POST /approvals/{id}/approve    - resume LangGraph interrupt
  POST /approvals/{id}/reject
"""

from fastapi import APIRouter

router = APIRouter()
