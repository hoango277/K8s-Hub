"""Tests for self-service password change and admin password reset.

No database: `revoke_all_sessions` is replaced with a fake that records whose
sessions were revoked — that is the most important effect to preserve, because
changing a password without kicking out old sessions lets whoever holds a
refresh token keep using it.
"""

from __future__ import annotations

import uuid

import pytest

from app.core.security import hash_password, verify_password
from app.db.models.user import User
from app.services import auth_service, user_service


class FakeSession:
    async def flush(self) -> None:
        return None


def make_user(password: str = "OldPassword123", role: str = "user") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        display_name="x",
        role=role,
        is_active=True,
        password_hash=hash_password(password),
    )


@pytest.fixture
def revoked(monkeypatch):
    """List of user_ids whose sessions were all revoked."""
    revoked_ids: list[uuid.UUID] = []

    async def fake_revoke_all_sessions(_db, user_id):
        revoked_ids.append(user_id)

    monkeypatch.setattr(auth_service, "revoke_all_sessions", fake_revoke_all_sessions)
    monkeypatch.setattr(user_service, "revoke_all_sessions", fake_revoke_all_sessions)
    return revoked_ids


# --------------------------------------------------------------------------
# Self-service password change
# --------------------------------------------------------------------------


async def test_change_password_succeeds_and_revokes_sessions(revoked):
    u = make_user()
    await auth_service.change_password(
        FakeSession(), u, current_password="OldPassword123", new_password="NewPassword456"
    )
    assert verify_password("NewPassword456", u.password_hash)
    assert not verify_password("OldPassword123", u.password_hash)
    assert revoked == [u.id]


async def test_wrong_current_password_does_not_change(revoked):
    u = make_user()
    old_hash = u.password_hash
    with pytest.raises(auth_service.InvalidPasswordError):
        await auth_service.change_password(
            FakeSession(), u, current_password="random-guess", new_password="NewPassword456"
        )
    assert u.password_hash == old_hash
    assert revoked == []


async def test_new_password_equal_to_old_is_rejected(revoked):
    u = make_user()
    with pytest.raises(auth_service.InvalidPasswordError):
        await auth_service.change_password(
            FakeSession(), u, current_password="OldPassword123", new_password="OldPassword123"
        )
    assert revoked == []


async def test_account_without_local_password_cannot_change_it(revoked):
    """A future OAuth-only account (password_hash=None) has no old password to
    verify — it must not be bypassed by sending an empty string."""
    u = make_user()
    u.password_hash = None
    with pytest.raises(auth_service.InvalidPasswordError):
        await auth_service.change_password(
            FakeSession(), u, current_password="", new_password="NewPassword456"
        )


# --------------------------------------------------------------------------
# Admin password reset
# --------------------------------------------------------------------------


async def test_admin_resets_another_users_password(revoked):
    admin, forgetful_user = make_user(role="admin"), make_user()
    await user_service.reset_password(
        FakeSession(), forgetful_user, actor=admin, new_password="TempPassword789"
    )
    assert verify_password("TempPassword789", forgetful_user.password_hash)
    assert revoked == [forgetful_user.id]


async def test_admin_cannot_reset_own_password(revoked):
    """This path does not ask for the old password — if it worked on yourself,
    anyone who got hold of an admin's access token could take over that account."""
    admin = make_user(role="admin")
    old_hash = admin.password_hash
    with pytest.raises(user_service.OperationBlockedError):
        await user_service.reset_password(
            FakeSession(), admin, actor=admin, new_password="TempPassword789"
        )
    assert admin.password_hash == old_hash
    assert revoked == []
