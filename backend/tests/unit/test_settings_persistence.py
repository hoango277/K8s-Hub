"""Tests for saving Settings-page changes and their history (settings_service).

No database: a fake session records what would be written.
"""

from __future__ import annotations

import uuid

from app.core.config import Settings
from app.db.models.setting import SettingChange, SettingOverride
from app.db.models.user import User
from app.services import settings_service as svc

KEY = "gsk_live_secret_value_123"


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows: list[SettingOverride] | None = None) -> None:
        self.rows = {r.name: r for r in rows or []}
        self.added: list = []
        self.deleted_statements = 0

    async def get(self, _model, name):
        return self.rows.get(name)

    def add(self, obj) -> None:
        self.added.append(obj)
        if isinstance(obj, SettingOverride):
            self.rows[obj.name] = obj

    async def execute(self, stmt):
        if stmt.is_delete:
            self.deleted_statements += 1
            return None
        return FakeResult(list(self.rows.values()))

    async def flush(self) -> None:
        return None


def _admin() -> User:
    return User(id=uuid.uuid4(), email="admin@example.com", display_name="A", role="admin")


def _cfg(**over) -> Settings:
    return Settings(_env_file=None, **{"JWT_SECRET": "test-secret", **over})


async def test_api_key_is_encrypted_at_rest(monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg())
    db = FakeSession()
    await svc.persist_changes(
        db,
        actor=_admin(),
        action="update",
        before_overrides={},
        after_overrides={"GROQ_API_KEY": KEY},
        before=_cfg(),
        after=_cfg(GROQ_API_KEY=KEY),
    )
    row = db.rows["GROQ_API_KEY"]
    assert row.secret is True
    assert KEY not in str(row.value)
    # ...and it comes back intact on the next start.
    assert await svc.load_overrides(db) == {"GROQ_API_KEY": KEY}


async def test_history_never_contains_the_key(monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg())
    db = FakeSession()
    await svc.persist_changes(
        db,
        actor=_admin(),
        action="update",
        before_overrides={},
        after_overrides={"GROQ_API_KEY": KEY},
        before=_cfg(),
        after=_cfg(GROQ_API_KEY=KEY),
    )
    [change] = [a for a in db.added if isinstance(a, SettingChange)]
    assert change.secret is True
    assert change.old_value is None and change.new_value is None
    assert change.actor_email == "admin@example.com"


async def test_history_records_effective_values_and_restore(monkeypatch):
    """Dropping an override is logged as 'restore', old value -> the .env value."""
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg())
    db = FakeSession()
    changed = await svc.persist_changes(
        db,
        actor=_admin(),
        action="update",
        before_overrides={"LLM_TEMPERATURE": 0.7},
        after_overrides={},
        before=_cfg(LLM_TEMPERATURE=0.7),
        after=_cfg(),
    )
    assert changed == ["LLM_TEMPERATURE"]
    assert db.deleted_statements == 1
    [change] = [a for a in db.added if isinstance(a, SettingChange)]
    assert (change.action, change.old_value, change.new_value) == ("restore", 0.7, 0.0)


async def test_unchanged_fields_are_not_logged(monkeypatch):
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg())
    db = FakeSession()
    changed = await svc.persist_changes(
        db,
        actor=_admin(),
        action="update",
        before_overrides={"LLM_MAX_RETRIES": 5},
        after_overrides={"LLM_MAX_RETRIES": 5, "LLM_TEMPERATURE": 0.2},
        before=_cfg(LLM_MAX_RETRIES=5),
        after=_cfg(LLM_MAX_RETRIES=5, LLM_TEMPERATURE=0.2),
    )
    assert changed == ["LLM_TEMPERATURE"]


async def test_key_saved_under_another_jwt_secret_is_skipped(monkeypatch):
    """Rotating JWT_SECRET must not stop the app — the key is ignored, not fatal."""
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg(JWT_SECRET="old-secret"))
    db = FakeSession()
    await svc.persist_changes(
        db,
        actor=_admin(),
        action="update",
        before_overrides={},
        after_overrides={"GROQ_API_KEY": KEY, "LLM_MAX_RETRIES": 4},
        before=_cfg(),
        after=_cfg(GROQ_API_KEY=KEY, LLM_MAX_RETRIES=4),
    )
    monkeypatch.setattr(svc, "get_settings", lambda: _cfg(JWT_SECRET="new-secret"))
    assert await svc.load_overrides(db) == {"LLM_MAX_RETRIES": 4}
