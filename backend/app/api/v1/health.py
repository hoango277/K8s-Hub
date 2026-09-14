"""Kiểm tra ứng dụng còn sống và các phụ thuộc có sẵn sàng không."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.db.session import check_connection

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Ứng dụng có đang chạy không. Nhẹ, không chạm vào phụ thuộc nào."""
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(response: Response) -> dict[str, Any]:
    """Đã sẵn sàng nhận việc chưa — có chạm cơ sở dữ liệu.

    Trả 503 nếu có phụ thuộc hỏng, để Kubernetes ngừng gửi lưu lượng vào.
    """
    db = await check_connection()
    if not db["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if db["ok"] else "degraded", "database": db}
