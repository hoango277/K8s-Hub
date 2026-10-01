"""Encrypt secrets stored in the database (provider API keys).

Fernet with a key derived from JWT_SECRET. Not a vault — whoever has both the
database and .env can decrypt — but a database dump or a read-only DB user no
longer hands out working credentials. If JWT_SECRET changes, stored secrets
can't be decrypted any more and must be entered again: callers catch
`InvalidToken` and skip the value instead of failing to start.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    # Domain-separated so this key is not simply "the JWT signing key".
    digest = hashlib.sha256(b"k8s-hub/settings/v1:" + get_settings().JWT_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_secret(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


__all__ = ["InvalidToken", "decrypt_secret", "encrypt_secret"]
