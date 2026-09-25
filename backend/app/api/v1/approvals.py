"""Human-in-the-loop approval gate.

TODO:
  GET  /approvals                 - queue of pending approvals
  GET  /approvals/{id}            - details + diff / dry-run output
  POST /approvals/{id}/approve    - resume LangGraph interrupt
  POST /approvals/{id}/reject
"""

from fastapi import APIRouter

router = APIRouter()
