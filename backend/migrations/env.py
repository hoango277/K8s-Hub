"""Môi trường chạy migration của Alembic.

Điểm khác so với bản mẫu Alembic sinh ra:

  - URL lấy từ `app.core.config`, không viết trong alembic.ini — để mật khẩu
    chỉ nằm ở .env, không lọt vào file được commit.
  - Ưu tiên ALEMBIC_DATABASE_URL nếu có. Migration cần khoá tư vấn của
    Postgres để hai người không chạy đè lên nhau, mà bộ gộp kết nối ở chế độ
    transaction thì không giữ được khoá đó qua nhiều câu lệnh.
  - Dùng engine bất đồng bộ vì cả dự án chạy asyncpg; không cài thêm driver
    đồng bộ chỉ để phục vụ migration.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import connect_args_for

# Import để mọi bảng có mặt trong Base.metadata trước khi so sánh.
import app.db.models  # noqa: F401  (bắt buộc, xem app/db/models/__init__.py)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    settings = get_settings()
    return settings.ALEMBIC_DATABASE_URL or settings.DATABASE_URL


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Không có hai dòng này thì đổi kiểu cột hay đổi giá trị mặc định
        # sẽ không được autogenerate phát hiện.
        compare_type=True,
        compare_server_default=True,
    )


def run_migrations_offline() -> None:
    """Chỉ sinh câu lệnh SQL ra màn hình, không kết nối. `alembic upgrade --sql`."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = database_url()
    engine = async_engine_from_config(
        {"sqlalchemy.url": url},
        prefix="sqlalchemy.",
        # Migration chạy một lần rồi thoát, không cần giữ pool.
        poolclass=pool.NullPool,
        connect_args=connect_args_for(url),
    )

    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
