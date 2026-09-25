"""Input/output types for the login and account management endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["admin", "engineer", "user"]


class RegisterRequest(BaseModel):
    """Self sign-up. There is NO role field — callers may not choose their own
    role; a new account is always 'user' (see app/api/v1/auth.py)."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    role: Role
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class TokenPair(BaseModel):
    """Returned after sign-up/login/refresh. `token_type` follows the OAuth2
    Bearer standard so the client can send `Authorization: Bearer <access_token>`."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserOut


class UserCreateByAdmin(BaseModel):
    """An admin creates an account for someone else — the role CAN be chosen,
    unlike RegisterRequest."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str = Field(min_length=1, max_length=120)
    role: Role = "user"


class ChangePasswordRequest(BaseModel):
    """Change your own password. The current password is REQUIRED — a leaked
    access token (an unlocked computer left unattended, a token leaked through
    logs) must not be enough to take over the account for good by setting a new
    password."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class ResetPasswordByAdmin(BaseModel):
    """An admin resets someone else's password (they forgot it). The old
    password is not needed — that is precisely why this path exists."""

    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=200)


class UpdateProfileRequest(BaseModel):
    """What anyone may change about THEIR OWN account.

    Only the display name. `extra="forbid"` matters here: without it, a body
    like {"display_name": "x", "role": "admin"} would be silently accepted
    minus the role — harmless today, but one careless `**payload` away from
    self-promotion. Rejecting unknown fields keeps it an explicit 422.
    """

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=120)


class UserUpdateByAdmin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Role | None = None
    is_active: bool | None = None
    display_name: str | None = Field(default=None, min_length=1, max_length=120)


__all__ = [
    "ChangePasswordRequest",
    "LoginRequest",
    "RefreshRequest",
    "RegisterRequest",
    "ResetPasswordByAdmin",
    "Role",
    "TokenPair",
    "UpdateProfileRequest",
    "UserCreateByAdmin",
    "UserOut",
    "UserUpdateByAdmin",
]
