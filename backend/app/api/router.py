"""Aggregate router: mounts every v1 feature router."""

from fastapi import APIRouter

from app.api.v1 import (
    approvals,
    chat,
    clusters,
    health,
    observability,
    rca,
    settings,
    skills,
)

api_router = APIRouter()

api_router.include_router(health.router, tags=["health"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(clusters.router, prefix="/clusters", tags=["clusters"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
api_router.include_router(rca.router, prefix="/rca", tags=["rca"])
api_router.include_router(skills.router, prefix="/skills", tags=["skills"])
api_router.include_router(observability.router, prefix="/observability", tags=["observability"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
