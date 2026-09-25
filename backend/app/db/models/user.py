"""System users and their login sessions (refresh tokens).

Three roles, from broadest to narrowest:

    admin     - edits system configuration, manages accounts, everything below
    engineer  - adds/edits/deletes skills and runbooks, everything below
    user      - Q&A (chat), runs existing skills/runbooks — may NOT add/edit/delete

The actual permission checks live in `app/api/deps.py` (`require_role`); this
file only declares data.

SELF SIGN-UP IS ALLOWED, but `POST /auth/register` ALWAYS assigns role='user' —
never trust a role field sent by the client in a sign-up request; that is how a
request crowns itself admin. Promotion to `engineer`/`admin` must go through
`PATCH /users/{id}` by a signed-in admin. The FIRST admin account (while the
database is still empty) is bootstrapped by `app/core/lifespan.py` from
`ADMIN_BOOTSTRAP_EMAIL`/`ADMIN_BOOTSTRAP_PASSWORD` in `.env`.

`password_hash` is nullable because GitHub/Google accounts (planned, not built
yet) will have no local password — OAuth login will need a separate
`oauth_accounts` table (user_id, provider, provider_account_id) so one person
can link several providers; that table is not built yet because there is no
client ID/secret to wire it to, and building it ahead of time would just leave
a dead skeleton.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.db.models.thread import ChatThread

ROLES = ("admin", "engineer", "user")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        # Constraint name kept as-is: it already exists in the migrations.
        CheckConstraint(
            "role IN ('admin', 'engineer', 'user')",
            name="role_hop_le",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # NULL until an admin sets the first password (or bootstrap does). The raw
    # password is never stored — it always goes through
    # `app.core.security.hash_password`.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Display only ("last signed in at..."), never used in authorization logic —
    # kept separate so `updated_at` is not touched every time a user merely
    # signs in without changing their profile.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    threads: Mapped[list[ChatThread]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    refresh_tokens: Mapped[list[RefreshToken]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class RefreshToken(Base, TimestampMixin):
    """A still-valid login session, stored so it can be revoked (real logout).

    The access token is a self-verifying JWT — the server does not hit the
    database on every request, which is why it is short-lived (60 minutes by
    default). The refresh token is the OPPOSITE: every use must look up this
    table, because its purpose is to allow revocation.

    The raw token is not stored, only `token_hash` (sha256) — if this table
    leaks (database breach, unencrypted backup), an attacker still cannot
    recover a usable token, exactly like the reason for not storing raw passwords.

    Rotation: on every successful refresh, the old row is marked `revoked_at`
    and a new row is created. If a revoked token is used again — a sign it has
    been stolen — the caller may choose to revoke every session of that user.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship(back_populates="refresh_tokens", lazy="raise")

    def __repr__(self) -> str:
        state = "revoked" if self.revoked_at else "active"
        return f"<RefreshToken {self.id} ({state})>"
