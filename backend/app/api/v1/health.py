"""Check that the app is alive and that its dependencies are ready."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.db.session import check_connection

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Is the app running? Cheap — touches no dependency."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(response: Response) -> dict[str, Any]:
    """Is the app ready to take work — this one does touch the database.

    Returns 503 if a dependency is broken, so Kubernetes stops sending traffic.
    """
    db = await check_connection()
    if not db["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if db["ok"] else "degraded", "database": db}
