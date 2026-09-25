"""Registration, login, session refresh, and account management (admin side).

This layer only touches the database and calls `app.core.security` — it knows
nothing about HTTP, following the same convention as `thread_service.py`. The
endpoints in `app/api/v1/auth.py` and `app/api/v1/users.py` just call down here
and translate to HTTP error codes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.models.user import RefreshToken, User


class AuthError(ValueError):
    """Wrong email/password, locked account, or invalid refresh token.

    Deliberately uses the SAME message for "no such email" and "wrong password"
    — distinguishing the two would reveal which emails are registered, exactly
    why `_thread_or_404` in chat.py does not distinguish "does not exist" from
    "belongs to someone else".
    """


class EmailAlreadyExistsError(AuthError):
    """Registering with an email that is already taken. This case is SAFE to
    state plainly: someone signing themselves up already knows their own email,
    so nothing extra is revealed."""


class InvalidPasswordError(AuthError):
    """The current password is wrong, or the new password equals the old one."""


async def _find_by_email(db: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email.lower())
    return (await db.execute(stmt)).scalar_one_or_none()


async def register(
    db: AsyncSession, *, email: str, password: str, display_name: str
) -> User:
    """Self sign-up. ALWAYS created with role='user' — see the app/db/models/user.py docstring."""
    if await _find_by_email(db, email):
        raise EmailAlreadyExistsError("This email is already registered.")

    user = User(
        email=email.lower(),
        display_name=display_name,
        role="user",
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate(db: AsyncSession, *, email: str, password: str) -> User:
    """Check email + password. Raises AuthError if wrong, if the account is
    locked, or if it has no local password (e.g. an account awaiting OAuth
    linking later on)."""
    user = await _find_by_email(db, email)
    if user is None or not verify_password(password, user.password_hash):
        raise AuthError("Incorrect email or password.")
    if not user.is_active:
        raise AuthError("This account has been locked.")

    user.last_login_at = datetime.now(UTC)
    await db.flush()
    return user


async def issue_token_pair(db: AsyncSession, user: User) -> tuple[str, str]:
    """Issue a fresh access + refresh token pair and store the (hashed) refresh
    token in the database."""
    access = create_access_token(user_id=user.id, role=user.role)
    refresh_raw, refresh_hash, expires_at = create_refresh_token(user_id=user.id)

    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return access, refresh_raw


async def refresh_token_pair(
    db: AsyncSession, *, user_id: uuid.UUID, raw_refresh_token: str
) -> tuple[str, str, User]:
    """Rotation: the old token is revoked and a new pair is issued.

    Must check BOTH `expires_at` AND `revoked_at`: natural expiry and revocation
    (logout, or detected reuse of an old token) are different reasons, but the
    consequence for the caller is the same — no new token is issued.
    """
    token_hash = hash_token(raw_refresh_token)
    stmt = select(RefreshToken).where(
        RefreshToken.token_hash == token_hash, RefreshToken.user_id == user_id
    )
    record = (await db.execute(stmt)).scalar_one_or_none()

    if record is None:
        raise AuthError("Invalid refresh token.")
    if record.revoked_at is not None:
        # A revoked token is being reused — a sign it was stolen. Revoke EVERY
        # other session of this user too, to lock out whoever holds the old token.
        #
        # MUST commit() RIGHT HERE, not wait for the endpoint to do it. The
        # endpoint will `raise HTTPException` right after this function raises
        # AuthError, and the `get_session` dependency (app/db/session.py)
        # rolls back on ANY exception that escapes the endpoint. Without a
        # commit here, the revocation itself — the most important defensive
        # action of this whole function — would be rolled back with it, and
        # whoever holds the stolen refresh token could keep using the other
        # sessions as usual.
        await revoke_all_sessions(db, user_id)
        await db.commit()
        raise AuthError("Refresh token has been revoked. All sessions have been signed out.")
    if record.expires_at < datetime.now(UTC):
        raise AuthError("Refresh token has expired.")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthError("This account is no longer active.")

    record.revoked_at = datetime.now(UTC)
    access, refresh_raw = await issue_token_pair(db, user)
    return access, refresh_raw, user


async def revoke_refresh_token(db: AsyncSession, *, raw_refresh_token: str) -> None:
    """Logout: revoke exactly one session. If it is not found, treat it as
    already signed out — no need to report an error."""
    token_hash = hash_token(raw_refresh_token)
    stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    record = (await db.execute(stmt)).scalar_one_or_none()
    if record is not None and record.revoked_at is None:
        record.revoked_at = datetime.now(UTC)
        await db.flush()


async def change_password(
    db: AsyncSession, user: User, *, current_password: str, new_password: str
) -> None:
    """A user changes their own password.

    Afterwards EVERY SESSION IS REVOKED, including the current one — the most
    common reason to change a password is suspecting someone else knows it, and
    in that case they very likely already hold a valid refresh token. Changing
    the password without kicking that session out would block nothing. The
    caller issues a fresh token pair for the current device so the user is not
    signed out along with it.
    """
    if not verify_password(current_password, user.password_hash):
        raise InvalidPasswordError("Current password is incorrect.")
    if current_password == new_password:
        raise InvalidPasswordError("New password must be different from the current one.")

    user.password_hash = hash_password(new_password)
    await revoke_all_sessions(db, user.id)


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Revoke every still-valid refresh token of a user — used when a token is
    detected as stolen, or when an admin locks someone's account."""
    stmt = select(RefreshToken).where(
        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
    )
    rows = (await db.execute(stmt)).scalars().all()
    now = datetime.now(UTC)
    for row in rows:
        row.revoked_at = now
    await db.flush()


__all__ = [
    "AuthError",
    "EmailAlreadyExistsError",
    "InvalidPasswordError",
    "authenticate",
    "change_password",
    "issue_token_pair",
    "refresh_token_pair",
    "register",
    "revoke_all_sessions",
    "revoke_refresh_token",
]
