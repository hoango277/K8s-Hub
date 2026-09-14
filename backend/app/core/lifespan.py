"""Việc chạy lúc bật và lúc tắt ứng dụng.

TODO: khởi tạo Redis, K8s client, Langfuse, danh mục kỹ năng MCP.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import get_settings
from app.db.session import check_connection, dispose_engine

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # --- bật ---
    config = get_settings()
    logger.info("Khởi động %s (môi trường: %s)", config.APP_NAME, config.APP_ENV)

    db = await check_connection()
    if db["ok"]:
        logger.info("Đã nối cơ sở dữ liệu: PostgreSQL %s", db["server_version"])
    else:
        # Không dừng ứng dụng: để nó chạy lên rồi báo lỗi qua endpoint sức khoẻ,
        # đỡ phải sửa .env rồi khởi động lại nhiều lần lúc đang phát triển.
        logger.error("KHÔNG nối được cơ sở dữ liệu: %s", db["error"])

    yield

    # --- tắt ---
    await dispose_engine()
    logger.info("Đã đóng mọi kết nối")
