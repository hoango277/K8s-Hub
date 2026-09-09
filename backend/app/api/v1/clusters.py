"""Cluster / K8s resource browsing endpoints (read-only).

TODO:
  GET /clusters                                  - danh sach cluster da dang ky
  GET /clusters/{id}/namespaces
  GET /clusters/{id}/resources                   - list theo kind
  GET /clusters/{id}/resources/{kind}/{name}     - describe
  GET /clusters/{id}/pods/{name}/logs            - stream logs
"""

from fastapi import APIRouter

router = APIRouter()
