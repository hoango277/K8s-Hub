"""Skill catalog + execution (runbook).

TODO:
  GET  /skills                    - catalog skill da dang ky
  GET  /skills/{name}             - manifest: mo ta, input schema, permission
  POST /skills/{name}/execute     - chay skill
  GET  /skills/executions/{id}    - trang thai + output
"""

from fastapi import APIRouter

router = APIRouter()
