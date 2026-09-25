"""Skill catalog + execution (runbook).

TODO:
  GET  /skills                    - catalog of registered skills
  GET  /skills/{name}             - manifest: description, input schema, permission
  POST /skills/{name}/execute     - run a skill
  GET  /skills/executions/{id}    - status + output
"""

from fastapi import APIRouter

router = APIRouter()
