"""All skills the system knows, in memory: built-in (repo) + custom (database).

Built-in skills are folders under `backend/skills/`, shipped with the code and
read-only on the web. Custom skills are created or imported on the Skills page
and stored in Postgres (app/services/skill_service.py loads them here at
startup and after every change).

In memory for the same reason as the tool registry: the chat agent asks for
the skill list synchronously on every turn.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.modules.skills.parser import SKILL_FILE, Skill, SkillFormatError, parse

logger = logging.getLogger(__name__)

BUILTIN_DIR = Path(__file__).resolve().parents[3] / "skills"


def load_builtin(directory: Path = BUILTIN_DIR) -> list[Skill]:
    """Every valid skill folder in the repo. A broken one is logged and skipped —
    one bad SKILL.md must not stop the app from starting."""
    skills: list[Skill] = []
    if not directory.is_dir():
        return skills
    for folder in sorted(p for p in directory.iterdir() if (p / SKILL_FILE).is_file()):
        files = {
            f.relative_to(folder).as_posix(): f.read_bytes()
            for f in folder.rglob("*")
            if f.is_file() and "__pycache__" not in f.parts
        }
        try:
            skills.append(parse(files, source="builtin", folder_name=folder.name))
        except SkillFormatError as exc:
            logger.warning("Skipping built-in skill %s: %s", folder.name, exc)
    return skills


class SkillStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._skills: dict[str, Skill] = {}
        self._enabled: dict[str, bool] = {}

    def load(self, skills: list[Skill], enabled: dict[str, bool]) -> None:
        with self._lock:
            self._skills = {s.name: s for s in skills}
            self._enabled = dict(enabled)

    def all(self) -> list[Skill]:
        with self._lock:
            return sorted(self._skills.values(), key=lambda s: s.name)

    def get(self, name: str) -> Skill | None:
        with self._lock:
            return self._skills.get(name)

    def is_enabled(self, name: str) -> bool:
        return self._enabled.get(name, True)

    def enabled(self) -> list[Skill]:
        return [s for s in self.all() if self.is_enabled(s.name)]

    def put(self, skill: Skill) -> None:
        with self._lock:
            self._skills[skill.name] = skill

    def remove(self, name: str) -> None:
        with self._lock:
            self._skills.pop(name, None)
            self._enabled.pop(name, None)

    def set_enabled(self, name: str, enabled: bool) -> None:
        with self._lock:
            self._enabled[name] = enabled


store = SkillStore()
# Usable before the database is reached (tests, a DB outage at startup).
store.load(load_builtin(), {})

__all__ = ["BUILTIN_DIR", "SkillStore", "load_builtin", "store"]
