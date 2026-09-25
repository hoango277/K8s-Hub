"""Password hashing, JWT issuing and verification.

Two different kinds of JWT that must NEVER be mixed up — `decode_token` also
checks the `type` claim so an access token cannot be used where a refresh token
is required, and vice versa:

    access token   - short-lived (JWT_EXPIRE_MINUTES), sent with every request,
                     self-verifying (the server does not hit the database).
    refresh token  - long-lived (JWT_REFRESH_EXPIRE_DAYS), used only to obtain
                     a new access token. The JWT itself only carries a token id;
                     whether that token is still valid or has been revoked must
                     be looked up in the `refresh_tokens` table (see
                     app/db/models/user.py) — because the whole point of a
                     refresh token is that it CAN be revoked mid-life.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

TokenType = Literal["access", "refresh"]

# bcrypt only uses the first 72 BYTES of a password and silently ignores the
# rest. For ASCII, 72 bytes = 72 characters, but passwords with diacritics (e.g.
# Vietnamese) are multi-byte UTF-8, so the real character limit is much shorter.
# Truncate HERE (a single place, applied both when hashing and when verifying)
# so no password ever gets its tail silently dropped by bcrypt without the user
# knowing.
_BCRYPT_MAX_BYTES = 72


class TokenError(ValueError):
    """Token is missing, malformed, expired, or of the wrong type (access used
    where refresh is expected)."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def _truncate_to_72_bytes(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_truncate_to_72_bytes(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Check a password. `password_hash=None` (OAuth-only account) always
    returns False.

    Does not raise when `password_hash` is empty or malformed — an account
    without a local password (bootstrap has not run yet, or later a GitHub/
    Google account) simply cannot log in with a password; that is not a system
    error.
    """
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_truncate_to_72_bytes(password), password_hash.encode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return False


# ---------------------------------------------------------------------------
# Access token — self-verifying JWT, no database lookup
# ---------------------------------------------------------------------------


def create_access_token(*, user_id: uuid.UUID, role: str) -> str:
    """Short-lived (JWT_EXPIRE_MINUTES).

    Carries `role` in the payload, but it is NOT used for authorization:
    `get_current_user` (app/api/deps.py) reloads the User from the database on
    every request and `require_role` compares against the `user.role` read
    there. That way a role change or account lock takes effect IMMEDIATELY on
    the next request, instead of waiting for the token to expire. The `role`
    claim in the JWT is only there for convenience when debugging.
    """
    config = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=config.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)


def create_refresh_token(*, user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """Generate a new refresh token.

    Returns (raw token to send to the client, token_hash to store in the
    database, expiry). The raw token is NOT stored — see the `RefreshToken`
    docstring for why.
    """
    config = get_settings()
    jti = secrets.token_urlsafe(32)  # random identifier, not a database id
    expires_at = datetime.now(UTC) + timedelta(days=config.JWT_REFRESH_EXPIRE_DAYS)

    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": datetime.now(UTC),
        "exp": expires_at,
    }
    token = jwt.encode(payload, config.JWT_SECRET, algorithm=config.JWT_ALGORITHM)
    return token, hash_token(token), expires_at


def hash_token(token: str) -> str:
    """sha256 of the raw token — used as the lookup key in refresh_tokens.

    sha256 (not bcrypt): the token already carries 256 bits of randomness on
    its own, so it does not need a deliberately slow algorithm the way a
    human-chosen password does. Speed is an advantage here: every refresh has
    to hash and then query the database.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def decode_token(token: str, *, expect: TokenType) -> dict[str, Any]:
    """Decode and verify a JWT. Raises `TokenError` if it is malformed, expired,
    or of the wrong type — callers do not need to tell those reasons apart, they
    only need to know it is "unusable"."""
    config = get_settings()
    try:
        payload = jwt.decode(token, config.JWT_SECRET, algorithms=[config.JWT_ALGORITHM])
    except JWTError as exc:
        raise TokenError(f"Invalid or expired token: {exc}") from exc

    if payload.get("type") != expect:
        raise TokenError(f"Expected a {expect!r} token, got {payload.get('type')!r}")

    return payload


__all__ = [
    "TokenError",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "hash_token",
    "verify_password",
]
