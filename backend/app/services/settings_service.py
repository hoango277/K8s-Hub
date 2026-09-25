"""Persistence, history and connection checks for the Settings page.

app/core/config.py owns the RUNNING configuration (sync, in memory). This file
makes it durable and accountable:

  - `persist_changes()` mirrors the in-memory overrides into
    `settings_overrides` and appends one `settings_changes` row per field that
    changed. Called by the settings endpoints right after `apply_overrides()`.
  - `load_overrides()` reads them back at startup (see app/core/lifespan.py).
  - `check_connections()` answers "is everything this app talks to reachable?"
    for the read-only Connections section.

API KEYS AT REST: encrypted with Fernet, using a key derived from JWT_SECRET.
Not a vault — anyone with both the database and .env can decrypt — but a
database dump or a read-only DB user no longer hands out working provider
keys. If JWT_SECRET changes, stored keys can't be decrypted: they are skipped
with a warning and must be entered again (the .env value applies meanwhile).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RUNTIME_EDITABLE_SECRETS, Settings, get_settings
from app.db.models.setting import SettingChange, SettingOverride
from app.db.models.user import User

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Encryption of secret values
# --------------------------------------------------------------------------


def _fernet() -> Fernet:
    # Domain-separated so this key is not simply "the JWT signing key".
    digest = hashlib.sha256(b"k8s-hub/settings/v1:" + get_settings().JWT_SECRET.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _encode(name: str, value: Any) -> Any:
    if name in RUNTIME_EDITABLE_SECRETS:
        return {"enc": _fernet().encrypt(str(value).encode()).decode()}
    return jsonable_encoder(value)


def _decode(row: SettingOverride) -> Any:
    if row.secret:
        token = (row.value or {}).get("enc", "")
        return _fernet().decrypt(token.encode()).decode()
    return row.value


# --------------------------------------------------------------------------
# Load / persist
# --------------------------------------------------------------------------


async def load_overrides(db: AsyncSession) -> dict[str, Any]:
    """Saved overrides, decrypted. Rows that can't be decrypted are skipped."""
    rows = (await db.execute(select(SettingOverride))).scalars().all()
    values: dict[str, Any] = {}
    for row in rows:
        try:
            values[row.name] = _decode(row)
        except (InvalidToken, AttributeError, ValueError):
            logger.warning(
                "Could not decrypt the saved value of %s (JWT_SECRET changed?). "
                "Ignoring it; enter it again on the Settings page.",
                row.name,
            )
    return values


async def persist_changes(
    db: AsyncSession,
    *,
    actor: User,
    action: str,
    before_overrides: dict[str, Any],
    after_overrides: dict[str, Any],
    before: Settings,
    after: Settings,
) -> list[str]:
    """Mirror the override diff into the database and log it. Does NOT commit.

    `before`/`after` are the EFFECTIVE configurations, so the history shows
    what the system actually ran with (a restore shows old override -> .env
    value), not just the raw override dicts.

    Returns the names of the fields that changed.
    """
    changed = sorted(
        name
        for name in set(before_overrides) | set(after_overrides)
        if before_overrides.get(name) != after_overrides.get(name)
    )

    for name in changed:
        is_secret = name in RUNTIME_EDITABLE_SECRETS
        if name in after_overrides:
            row = await db.get(SettingOverride, name)
            if row is None:
                row = SettingOverride(name=name)
                db.add(row)
            row.value = _encode(name, after_overrides[name])
            row.secret = is_secret
            row.updated_by = actor.id
        else:
            await db.execute(delete(SettingOverride).where(SettingOverride.name == name))

        field_action = action
        if action == "update" and name not in after_overrides:
            field_action = "restore"
        db.add(
            SettingChange(
                actor_id=actor.id,
                actor_email=actor.email,
                action=field_action,
                field=name,
                secret=is_secret,
                old_value=None if is_secret else jsonable_encoder(getattr(before, name)),
                new_value=None if is_secret else jsonable_encoder(getattr(after, name)),
            )
        )

    await db.flush()
    return changed


async def log_reload_env(db: AsyncSession, *, actor: User) -> None:
    db.add(SettingChange(actor_id=actor.id, actor_email=actor.email, action="reload_env"))
    await db.flush()


async def list_changes(
    db: AsyncSession, *, limit: int = 50, offset: int = 0
) -> tuple[Sequence[SettingChange], int]:
    total = int((await db.execute(select(func.count()).select_from(SettingChange))).scalar_one())
    stmt = (
        select(SettingChange)
        .order_by(SettingChange.changed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return (await db.execute(stmt)).scalars().all(), total


# --------------------------------------------------------------------------
# Connection checks
# --------------------------------------------------------------------------

CHECK_TIMEOUT = 4.0


def _db_target(url: str) -> str:
    """host:port/database — never the credentials."""
    try:
        u = make_url(url)
        return f"{u.host}:{u.port or 5432}/{u.database}"
    except Exception:
        return "(invalid DATABASE_URL)"


async def _timed(coro) -> tuple[Any, int]:
    start = time.perf_counter()
    result = await coro
    return result, int((time.perf_counter() - start) * 1000)


async def _check_database() -> dict[str, Any]:
    from app.db.session import check_connection

    result, ms = await _timed(asyncio.wait_for(check_connection(), CHECK_TIMEOUT))
    return {
        "ok": result["ok"],
        "version": f"PostgreSQL {result['server_version']}" if result["ok"] else None,
        "detail": None if result["ok"] else result.get("error"),
        "latency_ms": ms,
    }


async def _check_langfuse() -> dict[str, Any]:
    from app.modules.observability.langfuse_client import check_langfuse

    result, ms = await _timed(asyncio.wait_for(check_langfuse(), CHECK_TIMEOUT))
    if not result.get("enabled"):
        detail = "Disabled (LANGFUSE_ENABLED=false in .env)"
        return {"ok": None, "detail": detail, "latency_ms": None}
    return {
        "ok": bool(result.get("ok")),
        "detail": None if result.get("ok") else (result.get("error") or "Authentication failed"),
        "latency_ms": ms,
    }


async def _check_http(url: str) -> dict[str, Any]:
    """GET a buildinfo endpoint; both Prometheus and Loki expose one."""
    async with httpx.AsyncClient(timeout=CHECK_TIMEOUT) as client:
        resp, ms = await _timed(client.get(url))
    if resp.status_code != 200:
        return {"ok": False, "detail": f"HTTP {resp.status_code}", "latency_ms": ms}
    data = resp.json()
    version = (data.get("data") or {}).get("version") or data.get("version")
    return {"ok": True, "version": version, "detail": None, "latency_ms": ms}


async def _check_tempo(url: str) -> dict[str, Any]:
    # Optional: traces need Tempo plus instrumented apps, so an empty TEMPO_URL
    # is a normal "off" state, not a failure.
    if not url:
        return {"ok": None, "detail": "Not configured (TEMPO_URL in .env)", "latency_ms": None}
    return await _check_http(f"{url}/api/status/buildinfo")


async def _safe(check) -> dict[str, Any]:
    """A check must report a failure, never raise — one dead service must not
    hide the status of the others."""
    try:
        return await check
    except TimeoutError:
        detail = f"No answer within {CHECK_TIMEOUT:.0f} s"
        return {"ok": False, "detail": detail, "latency_ms": None}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "latency_ms": None}


async def check_connections() -> list[dict[str, Any]]:
    """Reachability of everything this backend talks to, checked in parallel."""
    config = get_settings()
    prom = config.PROMETHEUS_URL.rstrip("/")
    loki = config.LOKI_URL.rstrip("/")
    tempo = config.TEMPO_URL.strip().rstrip("/")
    specs = [
        (
            "database", "Database", "Accounts, conversations, settings",
            _db_target(config.DATABASE_URL), _check_database(),
        ),
        (
            "langfuse", "Langfuse", "Traces, token usage and cost of every AI turn",
            config.LANGFUSE_HOST, _check_langfuse(),
        ),
        (
            "prometheus", "Prometheus", "Cluster metrics used for diagnosis",
            prom, _check_http(f"{prom}/api/v1/status/buildinfo"),
        ),
        (
            "loki", "Loki", "Cluster logs used for diagnosis",
            loki, _check_http(f"{loki}/loki/api/v1/status/buildinfo"),
        ),
        (
            "tempo", "Tempo", "Request traces of apps on the cluster, used for diagnosis",
            tempo or "(not configured)", _check_tempo(tempo),
        ),
    ]
    results = await asyncio.gather(*(_safe(check) for *_, check in specs))
    return [
        {"id": sid, "name": name, "purpose": purpose, "target": target, "version": None, **result}
        for (sid, name, purpose, target, _), result in zip(specs, results, strict=True)
    ]


__all__ = [
    "check_connections",
    "list_changes",
    "load_overrides",
    "log_reload_env",
    "persist_changes",
]

