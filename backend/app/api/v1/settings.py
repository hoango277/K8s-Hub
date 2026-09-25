"""Read and change runtime configuration from the web UI.

Only fields in `RUNTIME_EDITABLE` can be edited. Secret values (API keys) can
be written but are NEVER read back.

Every change is saved to Postgres (`settings_overrides`) and recorded in the
append-only history (`settings_changes`), so it survives a restart and there
is always an answer to "who changed this, and when".

Permissions: anyone signed in may view (GET /settings) — engineers/users may
need to know which execution mode the system is in. CHANGING, the history and
the connection checks are admin-only.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.config import (
    ConfigUpdateError,
    apply_overrides,
    editable_fields,
    get_settings,
    reload_from_env,
    runtime_overrides,
    settings_version,
)
from app.db.models.user import User
from app.services import settings_service as svc

logger = logging.getLogger(__name__)

router = APIRouter()
Admin = Annotated[User, Depends(require_role("admin"))]


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


class ChangeOut(BaseModel):
    id: uuid.UUID
    changed_at: datetime
    actor_email: str
    action: str = Field(description="update | restore | reset_all | reload_env")
    field: str | None
    old_value: Any = None
    new_value: Any = None
    secret: bool


class ChangePage(BaseModel):
    items: list[ChangeOut]
    total: int


class ConnectionStatus(BaseModel):
    id: str
    name: str
    purpose: str
    target: str = Field(description="Address checked — never includes credentials")
    ok: bool | None = Field(description="null = not enabled, so not checked")
    version: str | None = None
    detail: str | None = None
    latency_ms: int | None = None


def _view() -> SettingsView:
    return SettingsView(
        version=settings_version(),
        fields=[FieldInfo(**f) for f in editable_fields()],
        overrides=runtime_overrides(),
    )


async def _apply_and_persist(
    db: DbSession, actor: User, action: str, values: dict[str, Any], *, replace: bool
) -> SettingsView:
    """Apply in memory, then save to the database — and undo the first if the
    second fails, so the page never shows a change that a restart would lose."""
    before_cfg = get_settings()
    before = runtime_overrides(redact_secrets=False)
    try:
        apply_overrides(values, replace=replace)
    except ConfigUpdateError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    try:
        await svc.persist_changes(
            db,
            actor=actor,
            action=action,
            before_overrides=before,
            after_overrides=runtime_overrides(redact_secrets=False),
            before=before_cfg,
            after=get_settings(),
        )
        await db.commit()
    except Exception as exc:
        logger.exception("Could not save settings to the database; reverting")
        await db.rollback()
        apply_overrides(before, replace=True)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Could not save to the database, so nothing was changed. Try again.",
        ) from exc
    return _view()


@router.get("", response_model=SettingsView)
async def read_settings(user: CurrentUser) -> SettingsView:
    """Editable fields, with their current value and the original .env value."""
    return _view()


@router.patch("", response_model=SettingsView)
async def update_settings(patch: SettingsPatch, db: DbSession, actor: Admin) -> SettingsView:
    """Apply changes. If one field is invalid the whole batch is rejected and
    nothing changes."""
    return await _apply_and_persist(db, actor, "update", patch.values, replace=patch.replace)


@router.post("/reset", response_model=SettingsView)
async def reset_settings(db: DbSession, actor: Admin) -> SettingsView:
    """Drop every change and go back to exactly what .env says."""
    return await _apply_and_persist(db, actor, "reset_all", {}, replace=True)


@router.post("/reload-env", response_model=SettingsView)
async def reload_env(db: DbSession, actor: Admin) -> SettingsView:
    """Re-read .env from disk. Changes made on the web are kept and re-applied on top."""
    reload_from_env()
    await svc.log_reload_env(db, actor=actor)
    await db.commit()
    return _view()


@router.get("/history", response_model=ChangePage)
async def read_history(
    db: DbSession,
    _actor: Admin,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ChangePage:
    """Who changed which setting, from what, to what — newest first."""
    items, total = await svc.list_changes(db, limit=limit, offset=offset)
    return ChangePage(items=[ChangeOut.model_validate(i, from_attributes=True) for i in items],
                      total=total)


@router.get("/status", response_model=list[ConnectionStatus])
async def read_status(_actor: Admin) -> list[ConnectionStatus]:
    """Whether the database, Langfuse, Prometheus, Loki and Tempo answer right now."""
    return [ConnectionStatus(**c) for c in await svc.check_connections()]


@router.get("/effective")
async def read_effective_settings(_actor: Admin) -> dict[str, Any]:
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
