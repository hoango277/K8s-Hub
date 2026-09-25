"""Account management — the admin side.

Unlike `auth_service.py` (self-service registration/login), this file holds the
operations ONLY an admin may call: list accounts, create an account on someone
else's behalf (with a choice of role), change roles, lock/unlock accounts.
Authorization is enforced at the endpoint layer (`require_role("admin")`); this
file assumes the caller has already been vetted.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.db.models.user import User
from app.services.auth_service import EmailAlreadyExistsError, revoke_all_sessions


class OperationBlockedError(ValueError):
    """The operation is valid data-wise but would leave the system without an
    administrator."""


async def _count_active_admins(db: AsyncSession) -> int:
    stmt = select(func.count()).select_from(User).where(
        User.role == "admin", User.is_active.is_(True)
    )
    return int((await db.execute(stmt)).scalar_one())


async def list_users(db: AsyncSession) -> Sequence[User]:
    stmt = select(User).order_by(User.created_at)
    return (await db.execute(stmt)).scalars().all()


async def create_user(
    db: AsyncSession, *, email: str, password: str, display_name: str, role: str
) -> User:
    """An admin creates an account on someone else's behalf — the role CAN be
    chosen up front, unlike `auth_service.register()` (self sign-up, always
    forced to role='user')."""
    stmt = select(User).where(User.email == email.lower())
    if (await db.execute(stmt)).scalar_one_or_none() is not None:
        raise EmailAlreadyExistsError("This email is already registered.")

    user = User(
        email=email.lower(),
        display_name=display_name,
        role=role,
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()
    return user


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    actor: User,
    role: str | None = None,
    is_active: bool | None = None,
    display_name: str | None = None,
) -> User:
    """Change a role or lock an account.

    Locking an account (is_active=False) ALSO REVOKES every signed-in session —
    otherwise the locked user could keep using their old access token until it
    expires on its own (up to JWT_EXPIRE_MINUTES minutes), and could still
    refresh new tokens if only the is_active flag changed without touching
    refresh_tokens.

    Two operations are blocked even though the data is valid, because their
    consequences cannot be undone from the UI — fixing them would require going
    straight to the database:

      - An admin demoting or locking themselves. One misclick and they lose
        admin rights in the middle of the session they are using.
      - Demoting or locking the LAST active admin. Then nobody could call
        /users to promote someone else, and the bootstrap in lifespan.py would
        not help either, because it only runs when the database has no admin
        at all — a locked admin still counts as "having one".
    """
    loses_admin = user.role == "admin" and user.is_active and (
        (role is not None and role != "admin") or is_active is False
    )
    if loses_admin:
        if user.id == actor.id:
            raise OperationBlockedError(
                "You cannot demote or lock your own account. "
                "Ask another admin to do this."
            )
        if await _count_active_admins(db) <= 1:
            raise OperationBlockedError(
                "This is the last active admin. Promote another account to "
                "admin first, then demote or lock this one."
            )

    if role is not None:
        user.role = role
    if display_name is not None:
        user.display_name = display_name
    if is_active is not None:
        user.is_active = is_active
        if not is_active:
            await revoke_all_sessions(db, user.id)

    await db.flush()
    return user


async def reset_password(db: AsyncSession, user: User, *, actor: User, new_password: str) -> None:
    """An admin resets someone else's password, e.g. when they forgot it.

    Not allowed on yourself: changing your own password must go through
    `/auth/change-password`, which requires the current password. Otherwise
    anyone who got hold of an admin's access token could change that admin's
    password without knowing the old one.

    Revokes every session of the affected user — whoever is signed in with the
    old password (possibly the very person who hijacked the account) is signed
    out immediately.
    """
    if user.id == actor.id:
        raise OperationBlockedError(
            "You cannot reset your own password here. Use the Account page — "
            "it requires your current password."
        )
    user.password_hash = hash_password(new_password)
    await revoke_all_sessions(db, user.id)
    await db.flush()


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def bootstrap_admin(db: AsyncSession, *, email: str, password: str) -> User | None:
    """Ensure there is AT LEAST one admin; called at startup (see app/core/lifespan.py).

    There is no public sign-up for the admin/engineer roles — the first one has
    to be created some other way. Three cases, checked in order:

      1. Some admin already exists             -> do nothing, return None.
      2. This email already exists (other role) -> PROMOTE it to admin instead
         of creating a duplicate account. Handy when the operator signed up
         first and only then set ADMIN_BOOTSTRAP_EMAIL to that same email.
      3. Nothing exists yet                    -> create a new one with role='admin'.

    This is the ONLY place in the system that creates an admin account without
    another admin approving it — acceptable because it only runs when the
    database has NO admin at all, and the values come from `.env` (read only at
    startup, not editable via the web).
    """
    has_admin = (await db.execute(select(User).where(User.role == "admin"))).first()
    if has_admin is not None:
        return None

    stmt = select(User).where(User.email == email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user is not None:
        user.role = "admin"
        await db.flush()
        return user

    user = User(
        email=email.lower(),
        display_name="Administrator",
        role="admin",
        password_hash=hash_password(password),
    )
    db.add(user)
    await db.flush()
    return user


__all__ = [
    "OperationBlockedError",
    "bootstrap_admin",
    "create_user",
    "get_user",
    "list_users",
    "reset_password",
    "update_user",
]
