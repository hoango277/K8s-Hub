"""Things shared across the API layer.

Collected in one place so endpoints only need to declare a type, instead of
fetching a database session or building a client themselves.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenError, decode_token
from app.db.models.user import User
from app.db.session import get_session
from app.services.user_service import get_user

logger = logging.getLogger(__name__)

DbSession = Annotated[AsyncSession, Depends(get_session)]

# --------------------------------------------------------------------------
# Users — Bearer token (Authorization: Bearer <access_token>)
# --------------------------------------------------------------------------

# `auto_error=False`: we return our own 401 with a clear, actionable message
# below, instead of FastAPI's generic default "Not authenticated".
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    db: DbSession,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """The user behind the access token in the `Authorization` header.

    The access token is SELF-VERIFYING (no database lookup to read the role —
    the role is already in the JWT), but we still have to load the User once to
    know whether the account is still `is_active`: a JWT does not invalidate
    itself when an admin locks someone out mid-session.
    """
    if cred is None:
        raise _unauthorized("Missing access token. Please sign in again.")

    try:
        payload = decode_token(cred.credentials, expect="access")
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise _unauthorized("Malformed token: 'sub' is missing or invalid.") from exc

    user = await get_user(db, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("This account no longer exists or has been locked.")

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def has_role(user: User, roles: tuple[str, ...] | list[str]) -> bool:
    """Whether `user` may do something reserved for `roles`.

    Admin ALWAYS passes, even when not listed. Without this, every future
    endpoint guarded by `require_role("engineer")` (adding skills, runbooks…)
    would lock the admin out unless its author remembered to also write
    "admin" — an easy thing to forget, and the admin is supposed to be able
    to do everything.
    """
    return user.role == "admin" or user.role in roles


def require_role(*roles: str):
    """Guard an endpoint by role. Admin always passes (see `has_role`).

    Use as a dependency:  `user: Annotated[User, Depends(require_role("engineer"))]`
    """

    async def check_role(user: CurrentUser) -> User:
        if not has_role(user, roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role {' or '.join(roles)}; this account is {user.role}",
            )
        return user

    return check_role


__all__ = ["CurrentUser", "DbSession", "get_current_user", "has_role", "require_role"]
