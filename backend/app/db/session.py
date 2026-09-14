"""Kết nối cơ sở dữ liệu.

Tạo engine bất đồng bộ và cung cấp phiên làm việc cho tầng API.

Lưu ý khi dùng Supabase (hoặc bất kỳ Postgres có pgbouncer đứng trước):

  - Cổng 5432 trên `db.<ref>.supabase.co` là kết nối TRỰC TIẾP, chỉ có IPv6.
    Mạng chỉ có IPv4 sẽ không nối được — khi đó dùng bộ gộp kết nối
    (`aws-<region>.pooler.supabase.com`).
  - Bộ gộp ở chế độ transaction KHÔNG hỗ trợ prepared statement, mà asyncpg
    thì mặc định dùng. Phải tắt bằng `statement_cache_size=0`, nếu không sẽ
    gặp lỗi `DuplicatePreparedStatementError` lúc chạy tải cao.
  - Supabase bắt buộc SSL.

Những chỗ này được xử lý tự động trong `connect_args_for()`.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings, on_reload

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _is_pooled(url: str) -> bool:
    """Kết nối có đi qua bộ gộp (pgbouncer) hay không."""
    return "pooler.supabase.com" in url or ":6543" in url


def _needs_ssl(url: str) -> bool:
    """Máy chủ ngoài internet thì bắt buộc SSL; chạy local thì không."""
    return not any(host in url for host in ("localhost", "127.0.0.1", "@db:", "@postgres:"))


def connect_args_for(url: str) -> dict[str, Any]:
    args: dict[str, Any] = {}

    if _needs_ssl(url):
        args["ssl"] = "require"

    if _is_pooled(url):
        # pgbouncer chế độ transaction không dùng được prepared statement.
        args["statement_cache_size"] = 0
        args["prepared_statement_cache_size"] = 0

    return args


def create_engine() -> AsyncEngine:
    """Dựng engine theo cấu hình hiện tại."""
    config = get_settings()
    url = config.DATABASE_URL

    if url.startswith("postgresql://"):
        raise ValueError(
            "DATABASE_URL phải dùng driver bất đồng bộ. "
            "Đổi 'postgresql://' thành 'postgresql+asyncpg://' trong .env."
        )

    pooled = _is_pooled(url)
    return create_async_engine(
        url,
        echo=config.DEBUG and config.APP_ENV == "local",
        # pool_pre_ping gửi một câu "SELECT 1" trước MỖI lần lấy kết nối ra
        # dùng. Với CSDL đặt cùng khu vực thì không đáng kể, nhưng ở đây mỗi
        # lượt đi-về mất 0,6-1 giây nên nó gần như nhân đôi thời gian của các
        # endpoint nhẹ. Thay bằng cách thải kết nối theo tuổi: `pool_recycle`
        # ngắn hơn nhiều so với thời gian pgbouncer tự ngắt kết nối rảnh.
        pool_pre_ping=not pooled,
        pool_recycle=300 if pooled else 1800,
        # Đi qua bộ gộp thì giữ pool NHỎ ở phía ứng dụng, nhưng đừng để chỉ
        # một kết nối: một trang chat mở ra là đã gọi song song vài API, mà mỗi
        # truy vấn tới Supabase mất vài trăm mili giây. Với pool bằng 1, các
        # truy vấn xếp hàng chờ nhau và trang mất 3-6 giây mới hiện — người
        # dùng tưởng bấm không ăn.
        pool_size=5,
        max_overflow=10 if not pooled else 5,
        connect_args=connect_args_for(url),
    )


def get_engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        _engine = create_engine()
        _sessionmaker = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """Dependency của FastAPI. Tự commit khi xong, tự rollback khi lỗi.

        @router.get("/threads")
        async def list_threads(db: AsyncSession = Depends(get_session)): ...
    """
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> dict[str, Any]:
    """Thử nối tới CSDL. Dùng cho lúc khởi động và endpoint kiểm tra sức khoẻ."""
    try:
        async with get_engine().connect() as conn:
            version = (await conn.execute(text("SHOW server_version"))).scalar_one()
            database = (await conn.execute(text("SELECT current_database()"))).scalar_one()
        return {"ok": True, "server_version": version, "database": database}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


async def dispose_engine() -> None:
    """Đóng mọi kết nối. Gọi lúc tắt ứng dụng."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _sessionmaker = None


@on_reload
def _reset_on_config_change() -> None:
    """Cấu hình đổi thì engine cũ có thể đang trỏ sai chỗ.

    Chỉ bỏ tham chiếu — không đóng được ở đây vì hàm này chạy đồng bộ.
    Kết nối cũ sẽ được trình dọn rác đóng lại.
    """
    global _engine, _sessionmaker
    if _engine is not None:
        logger.info("Cấu hình đổi, sẽ dựng lại kết nối CSDL ở lần dùng tới")
    _engine = None
    _sessionmaker = None


__all__ = [
    "check_connection",
    "connect_args_for",
    "create_engine",
    "dispose_engine",
    "get_engine",
    "get_session",
    "get_sessionmaker",
]
