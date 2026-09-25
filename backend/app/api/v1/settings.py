"""Read and change runtime configuration from the web UI.

Only fields in `RUNTIME_EDITABLE` can be edited. Secret values (API keys) can
be written but are NEVER read back.

Permissions: anyone signed in may view (GET) — engineers/users may need to know
which execution mode the system is in. CHANGING (PATCH/POST) is admin-only, per
the permission matrix: "admin edits system configuration, engineer/user read only".
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, require_role
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
_admin_only = Depends(require_role("admin"))


class FieldInfo(BaseModel):
    name: str
    type: str = Field(
        description="boolean | integer | number | string | enum | list | object | secret"
    )
    options: list[Any] | None = Field(default=None, description="Allowed values, if enum")
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: float | None = None
    exclusive_maximum: float | None = None
    secret: bool
    description: str
    value: Any = Field(default=None, description="Current value; null if secret")
    is_set: bool | None = Field(default=None, description="Whether the secret has been set")
    env_value: Any = Field(default=None, description="Original value from .env")
    overridden: bool = Field(description="Whether it currently differs from .env")


class SettingsView(BaseModel):
    version: int = Field(description="Bumped on every change; used to detect conflicts")
    fields: list[FieldInfo]
    overrides: dict[str, Any] = Field(description="Active overrides, secrets masked")


class SettingsPatch(BaseModel):
    """Set a field to null to drop its override, returning it to the .env value."""

    values: dict[str, Any]
    replace: bool = Field(
        default=False,
        description="True replaces all overrides, False merges into the existing ones",
    )


def _view() -> SettingsView:
    return SettingsView(
        version=settings_version(),
        fields=[FieldInfo(**f) for f in editable_fields()],
        overrides=runtime_overrides(),
    )


@router.get("", response_model=SettingsView)
async def read_settings(user: CurrentUser) -> SettingsView:
    """Editable fields, with their current value and the original .env value."""
    return _view()


@router.patch("", response_model=SettingsView, dependencies=[_admin_only])
async def update_settings(patch: SettingsPatch) -> SettingsView:
    """Apply changes. If one field is invalid the whole batch is rejected and
    nothing changes."""
    try:
        apply_overrides(patch.values, replace=patch.replace)
    except ConfigUpdateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _view()


@router.post("/reset", response_model=SettingsView, dependencies=[_admin_only])
async def reset_settings() -> SettingsView:
    """Drop every change and go back to exactly what .env says."""
    clear_overrides()
    return _view()


@router.post("/reload-env", response_model=SettingsView, dependencies=[_admin_only])
async def reload_env() -> SettingsView:
    """Re-read .env from disk. Changes made on the web are kept and re-applied on top."""
    reload_from_env()
    return _view()


@router.get("/effective", dependencies=[_admin_only])
async def read_effective_settings() -> dict[str, Any]:
    """The entire effective configuration, with every secret value masked.

    Used for diagnosis when you suspect the system is running with the wrong
    configuration.
    """
    data = get_settings().model_dump()
    for name, value in data.items():
        if any(k in name for k in ("KEY", "SECRET", "PASSWORD", "TOKEN")):
            data[name] = "***" if value else ""
    # Connection strings embed passwords
    for name in ("DATABASE_URL", "REDIS_URL"):
        if data.get(name):
            data[name] = "***"
    return data
