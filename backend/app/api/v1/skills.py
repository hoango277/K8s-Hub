"""Agent Skills: list, read, create, edit, import/export, run scripts.

    GET    /skills                          all skills (every role)
    GET    /skills/runs                     script run history (every role)
    POST   /skills                          create a skill              (engineer+)
    POST   /skills/import                   import a .zip               (engineer+)
    GET    /skills/{name}                   SKILL.md + file list (every role)
    PATCH  /skills/{name}                   enable / disable            (engineer+)
    DELETE /skills/{name}                   delete a custom skill       (engineer+)
    GET    /skills/{name}/export            download as .zip (every role)
    GET    /skills/{name}/files/{path}      one file (every role)
    PUT    /skills/{name}/files/{path}      create/replace a text file  (engineer+)
    DELETE /skills/{name}/files/{path}      delete a file               (engineer+)
    POST   /skills/{name}/run               run one of its scripts      (engineer+)

Editing is engineer+ because a skill's scripts run ON THE BACKEND (see
app/modules/skills/scripts.py): editing a skill means running code on this server.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import CurrentUser, DbSession, require_role
from app.db.models.user import User
from app.modules.skills.parser import SKILL_FILE, Skill, SkillFormatError
from app.modules.skills.store import store
from app.services import skill_service as svc

router = APIRouter()
Engineer = Annotated[User, Depends(require_role("engineer"))]


class FileInfo(BaseModel):
    path: str
    size: int


class SkillSummary(BaseModel):
    name: str
    description: str
    source: str = Field(description="builtin (repo folder) or custom (created on the web)")
    enabled: bool
    files: list[FileInfo]


class SkillDetail(SkillSummary):
    skill_md: str
    frontmatter: dict[str, Any]


class SkillCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    instructions: str = Field(default="", max_length=100_000)


class SkillPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


class FileContent(BaseModel):
    path: str
    text: str | None = Field(description="null when the file is binary")
    size: int


class FileWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(max_length=1_000_000)


class ScriptRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    script: str = Field(max_length=200)
    args: list[str] = Field(default_factory=list, max_length=20)


class RunOut(BaseModel):
    id: uuid.UUID
    skill: str
    script: str
    args: list[str]
    trigger: str
    actor_email: str
    ok: bool
    exit_code: int | None
    output: str
    duration_ms: int
    created_at: datetime


class RunPage(BaseModel):
    items: list[RunOut]
    total: int


def _skill_or_404(name: str) -> Skill:
    skill = store.get(name)
    if skill is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No skill named {name!r}.")
    return skill


def _detail(skill: Skill) -> SkillDetail:
    return SkillDetail(
        **svc.summary(skill),
        skill_md=skill.files[SKILL_FILE].decode("utf-8"),
        frontmatter=skill.frontmatter,
    )


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


# --- collection ---------------------------------------------------------------


@router.get("", response_model=list[SkillSummary])
async def list_skills(_user: CurrentUser) -> list[SkillSummary]:
    return [SkillSummary(**svc.summary(s)) for s in store.all()]


@router.get("/runs", response_model=RunPage)
async def list_runs(
    db: DbSession,
    _user: CurrentUser,
    skill: str | None = Query(None, max_length=64),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> RunPage:
    items, total = await svc.list_runs(db, skill=skill, limit=limit, offset=offset)
    return RunPage(
        items=[RunOut.model_validate(r, from_attributes=True) for r in items], total=total
    )


@router.post("", response_model=SkillDetail, status_code=status.HTTP_201_CREATED)
async def create_skill(payload: SkillCreate, db: DbSession, actor: Engineer) -> SkillDetail:
    try:
        skill = await svc.create_skill(
            db,
            actor=actor,
            name=payload.name,
            description=payload.description,
            instructions=payload.instructions,
        )
    except (svc.SkillServiceError, SkillFormatError) as exc:
        raise _bad_request(exc) from exc
    return _detail(skill)


@router.post("/import", response_model=SkillDetail, status_code=status.HTTP_201_CREATED)
async def import_skill(
    db: DbSession,
    actor: Engineer,
    file: Annotated[UploadFile, File(description="A .zip with one skill folder")],
    replace: bool = Query(False, description="Overwrite a custom skill with the same name"),
) -> SkillDetail:
    data = await file.read(svc.MAX_ZIP_BYTES + 1)
    try:
        skill = await svc.import_zip(db, actor=actor, data=data, replace=replace)
    except (svc.SkillServiceError, SkillFormatError) as exc:
        raise _bad_request(exc) from exc
    return _detail(skill)


# --- one skill ------------------------------------------------------------------


@router.get("/{name}", response_model=SkillDetail)
async def get_skill(name: str, _user: CurrentUser) -> SkillDetail:
    return _detail(_skill_or_404(name))


@router.patch("/{name}", response_model=SkillDetail)
async def update_skill(
    name: str, payload: SkillPatch, db: DbSession, actor: Engineer
) -> SkillDetail:
    try:
        await svc.set_enabled(db, actor=actor, name=name, enabled=payload.enabled)
    except svc.SkillServiceError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return _detail(_skill_or_404(name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(name: str, db: DbSession, _actor: Engineer) -> None:
    _skill_or_404(name)
    try:
        await svc.delete_skill(db, name=name)
    except svc.SkillServiceError as exc:
        raise _bad_request(exc) from exc


@router.get("/{name}/export")
async def export_skill(name: str, _user: CurrentUser) -> Response:
    skill = _skill_or_404(name)
    return Response(
        content=svc.export_zip(skill),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{skill.name}.zip"'},
    )


@router.get("/{name}/files/{path:path}", response_model=FileContent)
async def read_file(name: str, path: str, _user: CurrentUser) -> FileContent:
    skill = _skill_or_404(name)
    content = skill.files.get(path)
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} has no file {path}.")
    try:
        text: str | None = content.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    return FileContent(path=path, text=text, size=len(content))


@router.put("/{name}/files/{path:path}", response_model=SkillDetail)
async def write_file(
    name: str, path: str, payload: FileWrite, db: DbSession, actor: Engineer
) -> SkillDetail:
    _skill_or_404(name)
    try:
        skill = await svc.put_file(
            db, actor=actor, name=name, path=path, content=payload.text.encode()
        )
    except (svc.SkillServiceError, SkillFormatError) as exc:
        raise _bad_request(exc) from exc
    return _detail(skill)


@router.delete("/{name}/files/{path:path}", response_model=SkillDetail)
async def delete_file(name: str, path: str, db: DbSession, actor: Engineer) -> SkillDetail:
    _skill_or_404(name)
    try:
        skill = await svc.delete_file(db, actor=actor, name=name, path=path)
    except (svc.SkillServiceError, SkillFormatError) as exc:
        raise _bad_request(exc) from exc
    return _detail(skill)


@router.post("/{name}/run", response_model=RunOut)
async def run_script(
    name: str, payload: ScriptRunRequest, db: DbSession, actor: Engineer
) -> RunOut:
    _skill_or_404(name)
    try:
        row = await svc.run_manual(
            db, actor=actor, name=name, script=payload.script, args=payload.args
        )
    except (svc.SkillServiceError, SkillFormatError) as exc:
        raise _bad_request(exc) from exc
    return RunOut.model_validate(row, from_attributes=True)
