"""Agent Skills: persistence, import/export, and script runs.

The in-memory store (app/modules/skills/store.py) is what the agent reads on
every turn; this service is the only writer. Every mutation writes Postgres
first, then updates the store — so a failed commit never leaves the agent
using a skill that isn't saved.
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.skill import SkillFile, SkillRecord, SkillRun
from app.db.models.user import User
from app.db.session import get_sessionmaker
from app.modules.skills.parser import (
    SKILL_FILE,
    Skill,
    SkillFormatError,
    check_name,
    check_path,
    parse,
    render_skill_md,
)
from app.modules.skills.scripts import ScriptResult, run_script
from app.modules.skills.store import load_builtin, store

logger = logging.getLogger(__name__)

MAX_ZIP_BYTES = 10_000_000


class SkillServiceError(ValueError):
    """Rejected request. Message is user-facing."""


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


async def _custom_files(db: AsyncSession, name: str) -> dict[str, bytes]:
    rows = (await db.execute(select(SkillFile).where(SkillFile.skill_name == name))).scalars()
    return {r.path: r.content for r in rows}


async def load_into_store(db: AsyncSession) -> None:
    """Called at startup: built-in folders + custom skills + enabled flags."""
    records = (await db.execute(select(SkillRecord))).scalars().all()
    skills = load_builtin()
    builtin_names = {s.name for s in skills}
    for rec in records:
        if rec.source != "custom" or rec.name in builtin_names:
            continue
        try:
            skills.append(parse(await _custom_files(db, rec.name), source="custom"))
        except SkillFormatError as exc:
            logger.warning("Skipping stored skill %s: %s", rec.name, exc)
    store.load(skills, {r.name: r.enabled for r in records})


def _custom_or_error(name: str) -> Skill:
    skill = store.get(name)
    if skill is None:
        raise SkillServiceError(f"No skill named {name!r}.")
    if skill.source != "custom":
        raise SkillServiceError(
            "Built-in skills are part of the code (backend/skills/) and can't be edited here. "
            "Export it and import a copy under a new name to customise it."
        )
    return skill


async def _save_custom(db: AsyncSession, skill: Skill, actor: User, *, new: bool) -> None:
    if new:
        db.add(
            SkillRecord(
                name=skill.name,
                source="custom",
                enabled=True,
                created_by=actor.id,
                updated_by=actor.id,
            )
        )
    else:
        rec = await db.get(SkillRecord, skill.name)
        if rec is not None:
            rec.updated_by = actor.id
    await db.flush()
    await db.execute(delete(SkillFile).where(SkillFile.skill_name == skill.name))
    db.add_all(SkillFile(skill_name=skill.name, path=p, content=c) for p, c in skill.files.items())
    await db.flush()


# --------------------------------------------------------------------------
# Create / edit / delete
# --------------------------------------------------------------------------


async def create_skill(
    db: AsyncSession, *, actor: User, name: str, description: str, instructions: str
) -> Skill:
    check_name(name)
    if store.get(name) is not None:
        raise SkillServiceError(f"A skill named {name!r} already exists.")
    text = render_skill_md(name, description, instructions or "Describe the steps here.")
    skill = parse({SKILL_FILE: text.encode()}, source="custom")
    await _save_custom(db, skill, actor, new=True)
    await db.commit()
    store.put(skill)
    return skill


async def put_file(db: AsyncSession, *, actor: User, name: str, path: str, content: bytes) -> Skill:
    """Create or replace one file. SKILL.md is re-validated, and its `name` must not change."""
    current = _custom_or_error(name)
    files = {**current.files, check_path(path): content}
    skill = parse(files, source="custom", folder_name=name)
    await _save_custom(db, skill, actor, new=False)
    await db.commit()
    store.put(skill)
    return skill


async def delete_file(db: AsyncSession, *, actor: User, name: str, path: str) -> Skill:
    current = _custom_or_error(name)
    path = check_path(path)
    if path == SKILL_FILE:
        raise SkillServiceError("SKILL.md can't be deleted — delete the whole skill instead.")
    if path not in current.files:
        raise SkillServiceError(f"{name} has no file {path}.")
    files = {p: c for p, c in current.files.items() if p != path}
    skill = parse(files, source="custom", folder_name=name)
    await _save_custom(db, skill, actor, new=False)
    await db.commit()
    store.put(skill)
    return skill


async def set_enabled(db: AsyncSession, *, actor: User, name: str, enabled: bool) -> None:
    skill = store.get(name)
    if skill is None:
        raise SkillServiceError(f"No skill named {name!r}.")
    rec = await db.get(SkillRecord, name)
    if rec is None:  # a built-in skill that had no state yet
        rec = SkillRecord(name=name, source=skill.source, enabled=enabled, created_by=actor.id)
        db.add(rec)
    rec.enabled = enabled
    rec.updated_by = actor.id
    await db.commit()
    store.set_enabled(name, enabled)


async def delete_skill(db: AsyncSession, *, name: str) -> None:
    _custom_or_error(name)
    await db.execute(delete(SkillRecord).where(SkillRecord.name == name))
    await db.commit()
    store.remove(name)


# --------------------------------------------------------------------------
# Import / export (.zip in the standard folder layout)
# --------------------------------------------------------------------------


def export_zip(skill: Skill) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in sorted(skill.files.items()):
            zf.writestr(f"{skill.name}/{path}", content)
    return buf.getvalue()


def _read_zip(data: bytes) -> tuple[dict[str, bytes], str | None]:
    """Files of the skill inside a zip, accepting `<name>/SKILL.md` or `SKILL.md` at the root."""
    if len(data) > MAX_ZIP_BYTES:
        raise SkillServiceError("The file is larger than 10 MB.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise SkillServiceError("That is not a valid .zip file.") from exc
    entries = [i for i in zf.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
    if sum(i.file_size for i in entries) > MAX_ZIP_BYTES:  # zip bomb guard
        raise SkillServiceError("The skill is larger than 10 MB once unpacked.")
    names = [i.filename.replace("\\", "/") for i in entries]
    if SKILL_FILE in names:
        prefix, folder = "", None
    else:
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) != 1 or f"{next(iter(tops))}/{SKILL_FILE}" not in names:
            raise SkillServiceError(
                "The zip must contain one skill: SKILL.md at the root, or a single folder with "
                "SKILL.md inside."
            )
        folder = next(iter(tops))
        prefix = folder + "/"
    files = {
        n[len(prefix) :]: zf.read(i)
        for n, i in zip(names, entries, strict=True)
        if n.startswith(prefix) and n[len(prefix) :]
    }
    return files, folder


async def import_zip(db: AsyncSession, *, actor: User, data: bytes, replace: bool) -> Skill:
    files, folder = _read_zip(data)
    skill = parse(files, source="custom", folder_name=folder)
    existing = store.get(skill.name)
    if existing is not None:
        if existing.source != "custom":
            raise SkillServiceError(
                f"{skill.name!r} is a built-in skill; import it under another name."
            )
        if not replace:
            raise SkillServiceError(f"A skill named {skill.name!r} already exists.")
    await _save_custom(db, skill, actor, new=existing is None)
    await db.commit()
    store.put(skill)
    return skill


# --------------------------------------------------------------------------
# Script runs
# --------------------------------------------------------------------------


def _run_row(
    *,
    skill: str,
    script: str,
    args: list[str],
    result: ScriptResult,
    actor_email: str,
    trigger: str,
) -> SkillRun:
    return SkillRun(
        skill=skill,
        script=script,
        args=args,
        trigger=trigger,
        actor_email=actor_email,
        ok=result.ok,
        exit_code=result.exit_code,
        output=result.output,
        duration_ms=result.duration_ms,
    )


async def run_manual(
    db: AsyncSession, *, actor: User, name: str, script: str, args: list[str]
) -> SkillRun:
    skill = store.get(name)
    if skill is None:
        raise SkillServiceError(f"No skill named {name!r}.")
    result = await run_script(skill, script, args)
    row = _run_row(
        skill=name,
        script=script,
        args=args,
        result=result,
        actor_email=actor.email,
        trigger="manual",
    )
    db.add(row)
    await db.commit()
    return row


async def log_run_detached(
    *,
    skill: str,
    script: str,
    args: list[str],
    result: ScriptResult,
    actor_email: str,
    trigger: str,
) -> None:
    """Record a run made by the chat agent. Own session: a tool has no request session.
    A logging failure must not turn a successful script into a failed tool call."""
    try:
        async with get_sessionmaker()() as db:
            db.add(
                _run_row(
                    skill=skill,
                    script=script,
                    args=args,
                    result=result,
                    actor_email=actor_email,
                    trigger=trigger,
                )
            )
            await db.commit()
    except Exception:
        logger.exception("Could not record the run of %s/%s", skill, script)


async def list_runs(
    db: AsyncSession, *, skill: str | None, limit: int, offset: int
) -> tuple[Sequence[SkillRun], int]:
    stmt = select(SkillRun)
    count = select(func.count()).select_from(SkillRun)
    if skill:
        stmt, count = stmt.where(SkillRun.skill == skill), count.where(SkillRun.skill == skill)
    total = int((await db.execute(count)).scalar_one())
    rows = (
        (await db.execute(stmt.order_by(SkillRun.created_at.desc()).limit(limit).offset(offset)))
        .scalars()
        .all()
    )
    return rows, total


def summary(skill: Skill) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "source": skill.source,
        "enabled": store.is_enabled(skill.name),
        "files": [{"path": p, "size": len(c)} for p, c in sorted(skill.files.items())],
    }


__all__ = [
    "SkillServiceError",
    "create_skill",
    "delete_file",
    "delete_skill",
    "export_zip",
    "import_zip",
    "list_runs",
    "load_into_store",
    "log_run_detached",
    "put_file",
    "run_manual",
    "set_enabled",
    "summary",
]
