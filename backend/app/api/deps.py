"""Những thứ tầng API dùng chung.

Gom vào một chỗ để endpoint chỉ cần khai báo kiểu, không phải tự đi lấy
phiên CSDL hay tự dựng client.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import on_reload
from app.db.models.user import User
from app.db.session import get_session

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_session)]

# --------------------------------------------------------------------------
# Người dùng
# --------------------------------------------------------------------------

# CHƯA CÓ ĐĂNG NHẬP. Mọi thao tác tạm quy về một tài khoản duy nhất để hội
# thoại vẫn có chủ sở hữu hợp lệ trong CSDL. Khi làm xong đăng nhập (STT 32),
# chỉ cần thay ruột `get_current_user` — bảng và khoá ngoại giữ nguyên.
LOCAL_USER_EMAIL = "local@k8s-hub.dev"
LOCAL_USER_NAME = "Người dùng cục bộ"


# Nhớ sẵn tài khoản cục bộ sau lần tra đầu tiên.
#
# Vì sao đáng làm: mỗi lượt đi-về tới Supabase mất 0,6-1 giây (máy chủ đặt ở
# Sydney). Tra lại tài khoản ở MỌI request là cộng thêm chừng đó vào mọi thao
# tác, chỉ để đọc một dòng không bao giờ đổi.
#
# Đối tượng được tách khỏi phiên (`expunge`) nên dùng lại được ở request sau.
# Kèm theo đó là một giới hạn: KHÔNG gán nó vào quan hệ của đối tượng khác
# (`thread.user = user`) — hãy dùng `thread.user_id = user.id`.
_tai_khoan_cuc_bo: User | None = None
_khoa_tai_khoan = asyncio.Lock()


@on_reload
def _quen_tai_khoan() -> None:
    """Cấu hình đổi thì CSDL có thể đã khác, tài khoản nhớ sẵn không còn đúng."""
    global _tai_khoan_cuc_bo
    _tai_khoan_cuc_bo = None


async def get_current_user(db: DbSession) -> User:
    """Tài khoản đang thao tác.

    Tạm thời luôn trả về tài khoản cục bộ, tự tạo ở lần gọi đầu tiên.
    """
    global _tai_khoan_cuc_bo
    if _tai_khoan_cuc_bo is not None:
        return _tai_khoan_cuc_bo

    async with _khoa_tai_khoan:
        # Nhiều request cùng vào lúc khởi động: chỉ cái đầu tiên phải đi tra.
        if _tai_khoan_cuc_bo is not None:
            return _tai_khoan_cuc_bo

        stmt = select(User).where(User.email == LOCAL_USER_EMAIL)
        user = (await db.execute(stmt)).scalar_one_or_none()

        if user is None:
            user = User(
                email=LOCAL_USER_EMAIL,
                display_name=LOCAL_USER_NAME,
                role="admin",
            )
            db.add(user)
            try:
                await db.flush()
            except Exception:
                # Một tiến trình khác vừa tạo trước.
                await db.rollback()
                user = (await db.execute(stmt)).scalar_one_or_none()
                if user is None:
                    raise
            logger.info("Đã tạo tài khoản cục bộ %s", LOCAL_USER_EMAIL)

        db.expunge(user)
        _tai_khoan_cuc_bo = user
        return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    """Chặn endpoint theo vai trò.

    CHƯA DÙNG Ở ĐÂU vì chưa có đăng nhập. Để sẵn cho các endpoint ghi — đổi
    cấu hình, duyệt thao tác lên cụm — khi làm xong phần đăng nhập.
    """

    async def kiem_tra(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Cần vai trò {' hoặc '.join(roles)}, tài khoản đang là {user.role}",
            )
        return user

    return kiem_tra


__all__ = ["CurrentUser", "DbSession", "get_current_user", "require_role"]
