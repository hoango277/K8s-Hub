"""Đọc và đổi cấu hình lúc chạy từ giao diện web.

Chỉ những trường trong `RUNTIME_EDITABLE` mới sửa được. Giá trị bí mật
(khoá API) ghi vào được nhưng KHÔNG bao giờ đọc ra.

TODO: gắn kiểm tra quyền — chỉ vai trò quản trị mới được gọi PATCH/POST.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import (
    ConfigUpdateError,
    apply_overrides,
    clear_overrides,
    editable_fields,
    get_settings,
    reload_from_env,
    runtime_overrides,
    settings_version,
)

router = APIRouter()


class FieldInfo(BaseModel):
    name: str
    type: str = Field(
        description="boolean | integer | number | string | enum | list | object | secret"
    )
    options: list[Any] | None = Field(default=None, description="Giá trị cho phép, nếu là enum")
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    secret: bool
    description: str
    value: Any = Field(default=None, description="Giá trị hiện tại; null nếu là bí mật")
    is_set: bool | None = Field(default=None, description="Bí mật đã được đặt chưa")
    env_value: Any = Field(default=None, description="Giá trị gốc trong .env")
    overridden: bool = Field(description="Đang bị đổi so với .env hay không")


class SettingsView(BaseModel):
    version: int = Field(description="Tăng sau mỗi lần đổi; dùng để phát hiện xung đột")
    fields: list[FieldInfo]
    overrides: dict[str, Any] = Field(description="Phần đang ghi đè, bí mật đã che")


class SettingsPatch(BaseModel):
    """Đặt một trường thành null để bỏ ghi đè, trả nó về giá trị trong .env."""

    values: dict[str, Any]
    replace: bool = Field(
        default=False,
        description="True thì thay toàn bộ phần ghi đè, False thì trộn vào cái đang có",
    )


def _view() -> SettingsView:
    return SettingsView(
        version=settings_version(),
        fields=[FieldInfo(**f) for f in editable_fields()],
        overrides=runtime_overrides(),
    )


@router.get("", response_model=SettingsView)
async def read_settings() -> SettingsView:
    """Danh sách trường đổi được, kèm giá trị hiện tại và giá trị gốc trong .env."""
    return _view()


@router.patch("", response_model=SettingsView)
async def update_settings(patch: SettingsPatch) -> SettingsView:
    """Áp dụng thay đổi. Sai một trường thì cả lô bị từ chối, không đổi gì."""
    try:
        apply_overrides(patch.values, replace=patch.replace)
    except ConfigUpdateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _view()


@router.post("/reset", response_model=SettingsView)
async def reset_settings() -> SettingsView:
    """Bỏ hết thay đổi, quay về đúng những gì ghi trong .env."""
    clear_overrides()
    return _view()


@router.post("/reload-env", response_model=SettingsView)
async def reload_env() -> SettingsView:
    """Đọc lại .env từ đĩa. Phần đã đổi trên web được giữ và áp lại lên trên."""
    reload_from_env()
    return _view()


@router.get("/effective")
async def read_effective_settings() -> dict[str, Any]:
    """Toàn bộ cấu hình đang có hiệu lực, đã che mọi giá trị bí mật.

    Dùng để chẩn đoán khi nghi hệ thống đang chạy sai cấu hình.
    """
    data = get_settings().model_dump()
    for name, value in data.items():
        if any(k in name for k in ("KEY", "SECRET", "PASSWORD", "TOKEN")):
            data[name] = "***" if value else ""
    # Chuỗi kết nối có nhúng mật khẩu
    for name in ("DATABASE_URL", "REDIS_URL"):
        if data.get(name):
            data[name] = "***"
    return data
