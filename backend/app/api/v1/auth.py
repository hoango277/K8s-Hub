"""Registration, login, session refresh, logout.

    POST /auth/register   self sign-up — always created with role='user'
    POST /auth/login      email + password -> access/refresh token pair
    POST /auth/refresh    old refresh token -> new pair (rotation)
    POST /auth/logout     revoke a refresh token
    POST /auth/change-password   change your own password (requires the current one)
    GET  /auth/me          your own profile, so the frontend can bootstrap the session
    PATCH /auth/me         change your own display name
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, DbSession
from app.core.security import TokenError, decode_token
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UpdateProfileRequest,
    UserOut,
)
from app.services import auth_service as svc

router = APIRouter()


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> TokenPair:
    try:
        user = await svc.register(
            db,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except svc.EmailAlreadyExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    access, refresh = await svc.issue_token_pair(db, user)
    await db.commit()  # commit before returning tokens — see chat.py::create_thread for why
    return TokenPair(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, db: DbSession) -> TokenPair:
    try:
        user = await svc.authenticate(db, email=payload.email, password=payload.password)
    except svc.AuthError as exc:
        # Same error code for "no such account" and "wrong password" — see the
        # AuthError docstring in auth_service.py.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    access, refresh = await svc.issue_token_pair(db, user)
    await db.commit()
    return TokenPair(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenPair:
    """No Bearer access token needed — the refresh token stands on its own,
    because its whole purpose is to obtain a NEW access token once the old one
    has expired."""
    try:
        claims = decode_token(payload.refresh_token, expect="refresh")
    except TokenError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Malformed token.") from exc

    try:
        access, new_refresh, user = await svc.refresh_token_pair(
            db, user_id=user_id, raw_refresh_token=payload.refresh_token
        )
    except svc.AuthError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc

    await db.commit()
    return TokenPair(
        access_token=access, refresh_token=new_refresh, user=UserOut.model_validate(user)
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, db: DbSession) -> None:
    await svc.revoke_refresh_token(db, raw_refresh_token=payload.refresh_token)
    await db.commit()


@router.post("/change-password", response_model=TokenPair)
async def change_password(
    payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
) -> TokenPair:
    """Change the password, sign out every other device, and return a NEW token
    pair for the current device — so the person who just changed it is not
    kicked out along with them."""
    try:
        await svc.change_password(
            db,
            user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except svc.InvalidPasswordError as exc:
        # 400, not 401: the caller IS still validly signed in, they just typed
        # the old password wrong. Returning 401 would make the frontend's
        # lib/api.ts think the session expired, clear the tokens, and bounce the
        # user to the login page.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    access, refresh = await svc.issue_token_pair(db, user)
    await db.commit()
    return TokenPair(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UpdateProfileRequest, db: DbSession, user: CurrentUser) -> UserOut:
    """Change your own display name — open to every role, unlike PATCH /users/{id}."""
    user.display_name = payload.display_name.strip() or user.display_name
    await db.commit()
    return UserOut.model_validate(user)


__all__ = ["router"]
