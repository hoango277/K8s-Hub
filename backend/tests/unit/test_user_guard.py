"""Tests for the blocking rules in `user_service.update_user`,
plus the "admin passes every role check" rule in `deps.has_role`.

Both are "valid data, but the consequences cannot be undone from the UI"
situations: an admin locking themselves out, or the system losing its last
admin. No database — the admin-counting function is replaced with a fake, and
the database session only needs `flush()`.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.models.user import User
from app.services import user_service as svc


class FakeSession:
    async def flush(self) -> None:
        return None


def make_user(role: str = "admin", *, active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        display_name="x",
        role=role,
        is_active=active,
    )


@pytest.fixture
def active_admins(monkeypatch):
    """Set the number of active admins that `update_user` will see."""

    def set_count(n: int) -> None:
        async def fake_count(_db):
            return n

        monkeypatch.setattr(svc, "_count_active_admins", fake_count)

    return set_count


async def test_admin_cannot_demote_self(active_admins):
    active_admins(3)
    me = make_user("admin")
    with pytest.raises(svc.OperationBlockedError):
        await svc.update_user(FakeSession(), me, actor=me, role="user")
    assert me.role == "admin"


async def test_admin_cannot_lock_self(active_admins):
    active_admins(3)
    me = make_user("admin")
    with pytest.raises(svc.OperationBlockedError):
        await svc.update_user(FakeSession(), me, actor=me, is_active=False)
    assert me.is_active is True


async def test_cannot_demote_last_admin(active_admins):
    active_admins(1)
    me, other = make_user("admin"), make_user("admin")
    with pytest.raises(svc.OperationBlockedError):
        await svc.update_user(FakeSession(), other, actor=me, role="engineer")


async def test_demoting_another_admin_is_allowed_when_admins_remain(active_admins):
    active_admins(2)
    me, other = make_user("admin"), make_user("admin")
    await svc.update_user(FakeSession(), other, actor=me, role="engineer")
    assert other.role == "engineer"


async def test_admin_can_still_rename_self(active_admins):
    """The guard blocks LOSING ADMIN RIGHTS, not every operation on yourself."""
    active_admins(1)
    me = make_user("admin")
    await svc.update_user(FakeSession(), me, actor=me, display_name="New name")
    assert me.display_name == "New name"


async def test_promoting_user_to_engineer_is_not_blocked(active_admins):
    active_admins(1)
    me, other = make_user("admin"), make_user("user")
    await svc.update_user(FakeSession(), other, actor=me, role="engineer")
    assert other.role == "engineer"


# --- has_role: admin passes every role check -----------------------------------


@pytest.mark.parametrize("required", [("admin",), ("engineer",), ("user",), ("engineer", "user")])
def test_admin_passes_every_role_check(required):
    from app.api.deps import has_role

    assert has_role(make_user("admin"), required)


def test_other_roles_only_pass_when_listed():
    from app.api.deps import has_role

    assert has_role(make_user("engineer"), ("engineer",))
    assert not has_role(make_user("engineer"), ("admin",))
    assert not has_role(make_user("user"), ("engineer",))
