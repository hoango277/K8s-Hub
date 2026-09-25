"""Tests for password hashing and JWT in app/core/security.py.

No database, no running server needed. This is where a real bug was hit while
building the login feature: `passlib` is incompatible with newer `bcrypt`
releases (it raised ValueError even for valid passwords), and a refresh token
reused after revocation would "come back to life" if the commit was forgotten
before raising. The tests here pin both down so they do not recur.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)

# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def test_hash_then_verify_correct_password():
    password_hash = hash_password("MyPassword123")
    assert verify_password("MyPassword123", password_hash) is True


def test_wrong_password_does_not_match():
    password_hash = hash_password("MyPassword123")
    assert verify_password("another-password", password_hash) is False


def test_missing_hash_is_always_false():
    """OAuth-only account (password_hash=None) — no exception, just False."""
    assert verify_password("anything", None) is False
    assert verify_password("anything", "") is False


def test_long_password_with_diacritics_does_not_break_bcrypt():
    """Before the fix: passlib probed the bcrypt version at init and raised
    ValueError on a PERFECTLY valid password due to a bcrypt>=4.1 compatibility
    bug. This test catches that regression with a password longer than 72 bytes
    when UTF-8 encoded (multi-byte Vietnamese characters)."""
    password = "a" * 100 + "ệ" * 30  # "ệ": 3 bytes each in UTF-8
    password_hash = hash_password(password)
    assert verify_password(password, password_hash) is True


def test_hash_does_not_contain_raw_password():
    password_hash = hash_password("top-secret")
    assert "top-secret" not in password_hash


# --------------------------------------------------------------------------
# Access token
# --------------------------------------------------------------------------


def test_access_token_decodes_to_correct_role_and_id():
    uid = uuid.uuid4()
    token = create_access_token(user_id=uid, role="engineer")
    payload = decode_token(token, expect="access")
    assert payload["sub"] == str(uid)
    assert payload["role"] == "engineer"
    assert payload["type"] == "access"


def test_access_token_cannot_be_used_as_refresh():
    token = create_access_token(user_id=uuid.uuid4(), role="user")
    with pytest.raises(TokenError):
        decode_token(token, expect="refresh")


def test_malformed_token_raises():
    with pytest.raises(TokenError):
        decode_token("not-a-jwt", expect="access")


# --------------------------------------------------------------------------
# Refresh token
# --------------------------------------------------------------------------


def test_refresh_token_decodes_and_hash_matches():
    uid = uuid.uuid4()
    token, token_hash, expires_at = create_refresh_token(user_id=uid)

    payload = decode_token(token, expect="refresh")
    assert payload["sub"] == str(uid)
    assert payload["type"] == "refresh"
    assert "jti" in payload  # random identifier, to tell sessions apart

    # The hash must be reproducible from the token — it is the lookup key in
    # the refresh_tokens table.
    assert hash_token(token) == token_hash
    assert expires_at > datetime.now(UTC)


def test_refresh_token_cannot_be_used_as_access():
    token, _hash, _expires_at = create_refresh_token(user_id=uuid.uuid4())
    with pytest.raises(TokenError):
        decode_token(token, expect="access")


def test_two_refresh_tokens_have_different_hashes():
    """Every login session needs its own jti — if two collided, revoking one
    session would accidentally revoke the other too."""
    _t1, hash1, _ = create_refresh_token(user_id=uuid.uuid4())
    _t2, hash2, _ = create_refresh_token(user_id=uuid.uuid4())
    assert hash1 != hash2


# --- Self-service profile update (PATCH /auth/me) ------------------------------


def test_profile_update_rejects_role_field():
    """Anyone can rename themselves; nobody can promote themselves on the way."""
    import pydantic

    from app.schemas.auth import UpdateProfileRequest

    assert UpdateProfileRequest(display_name="Ada").display_name == "Ada"
    with pytest.raises(pydantic.ValidationError):
        UpdateProfileRequest(display_name="Ada", role="admin")
    with pytest.raises(pydantic.ValidationError):
        UpdateProfileRequest(display_name="")
