"""Account management — every endpoint here is admin-ONLY.

    GET   /users           list accounts
    POST  /users           admin creates an account on someone's behalf (role can be chosen)
    PATCH /users/{id}      change role, lock/unlock, change display name
    POST  /users/{id}/reset-password   reset the password (user forgot it)

There is no DELETE, by decision: accounts are only ever locked
(is_active=false). A hard delete would also wipe that person's chat history
(ON DELETE CASCADE on chat_threads) and cannot be undone; locking can.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import CurrentUser, DbSession, require_role
from app.schemas.auth import ResetPasswordByAdmin, UserCreateByAdmin, UserOut, UserUpdateByAdmin
from app.services import auth_service, user_service

# `dependencies=` applies to EVERY route on this router — no route in this file
# can end up unguarded just because whoever added it forgot a per-route Depends().
router = APIRouter(dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=list[UserOut])
async def list_users(db: DbSession) -> Any:
    return await user_service.list_users(db)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreateByAdmin, db: DbSession) -> Any:
    try:
        user = await user_service.create_user(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
            role=payload.role,
        )
    except auth_service.EmailAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, payload: UserUpdateByAdmin, db: DbSession, actor: CurrentUser
) -> Any:
    user = await user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    try:
        updated = await user_service.update_user(
            db,
            user,
            actor=actor,
            role=payload.role,
            is_active=payload.is_active,
            display_name=payload.display_name,
        )
    except user_service.OperationBlockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return updated


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    user_id: uuid.UUID, payload: ResetPasswordByAdmin, db: DbSession, actor: CurrentUser
) -> None:
    user = await user_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
    try:
        await user_service.reset_password(db, user, actor=actor, new_password=payload.new_password)
    except user_service.OperationBlockedError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()


__all__ = ["router"]
