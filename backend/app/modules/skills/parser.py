"""Read and validate skills in the Agent Skills format.

A skill is a folder:

    <name>/
      SKILL.md          YAML front matter (at least `name`, `description`) + instructions
      scripts/          optional — code the agent can run (run_skill_script)
      references/       optional — documents the agent reads when needed
      assets/           optional — templates, examples, other files

The same format Claude Code and other agents use, so a skill written here can
be exported as a .zip and used there, and the other way round.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

SKILL_FILE = "SKILL.md"
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
NAME_MAX = 64
DESCRIPTION_MAX = 1024
RESERVED_WORDS = ("anthropic", "claude")

MAX_FILE_BYTES = 1_000_000
MAX_SKILL_BYTES = 5_000_000
MAX_FILES = 200


class SkillFormatError(ValueError):
    """The skill doesn't follow the format. Message is user-facing."""


@dataclass
class Skill:
    name: str
    description: str
    body: str
    frontmatter: dict[str, Any]
    #: path (posix, relative) -> content. Always contains SKILL.md.
    files: dict[str, bytes] = field(default_factory=dict)
    source: str = "custom"  # "builtin" (repo folder) | "custom" (created on the web)

    def other_files(self) -> list[str]:
        return sorted(p for p in self.files if p != SKILL_FILE)

    def scripts(self) -> list[str]:
        return [p for p in self.other_files() if p.startswith("scripts/")]


def check_name(name: str) -> str:
    if not name or len(name) > NAME_MAX or not NAME.match(name):
        raise SkillFormatError(
            "The name must be 1–64 characters: lowercase letters, digits and single hyphens "
            "(e.g. diagnose-crashloop)."
        )
    if any(word in name for word in RESERVED_WORDS):
        raise SkillFormatError(
            "The name must not contain the reserved words 'anthropic' or 'claude'."
        )
    return name


def check_path(path: str) -> str:
    """A safe, relative, posix path inside the skill folder."""
    p = PurePosixPath(path.replace("\\", "/"))
    if (
        not path
        or p.is_absolute()
        or any(part in ("..", "") for part in p.parts)
        or ":" in p.parts[0]
        or len(path) > 200
    ):
        raise SkillFormatError(
            f"Invalid file path: {path!r}. Use a relative path inside the skill."
        )
    return str(p)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        raise SkillFormatError("SKILL.md must start with a YAML front matter block (---).")
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise SkillFormatError("The YAML front matter in SKILL.md is not closed with ---.")
    header = parts[0][3:]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    try:
        data = yaml.safe_load(header) or {}
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"The YAML front matter is not valid: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillFormatError("The YAML front matter must be a mapping (key: value).")
    return data, body.strip()


def parse(files: dict[str, bytes], *, source: str, folder_name: str | None = None) -> Skill:
    """Validate a whole skill and return it. `folder_name`, when known, must equal `name`."""
    files = {check_path(p): c for p, c in files.items()}
    if SKILL_FILE not in files:
        raise SkillFormatError("A skill needs a SKILL.md file at its root.")
    if len(files) > MAX_FILES:
        raise SkillFormatError(f"Too many files (max {MAX_FILES}).")
    big = next((p for p, c in files.items() if len(c) > MAX_FILE_BYTES), None)
    if big:
        raise SkillFormatError(f"{big} is larger than 1 MB.")
    if sum(len(c) for c in files.values()) > MAX_SKILL_BYTES:
        raise SkillFormatError("The skill is larger than 5 MB in total.")

    try:
        text = files[SKILL_FILE].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SkillFormatError("SKILL.md must be UTF-8 text.") from exc
    meta, body = split_frontmatter(text)

    name = check_name(str(meta.get("name") or ""))
    if folder_name is not None and folder_name != name:
        raise SkillFormatError(
            f"The name in SKILL.md ({name!r}) must match the folder name ({folder_name!r})."
        )
    description = str(meta.get("description") or "").strip()
    if not description:
        raise SkillFormatError(
            "SKILL.md needs a description: what the skill does and when to use it."
        )
    if len(description) > DESCRIPTION_MAX:
        raise SkillFormatError(f"The description is longer than {DESCRIPTION_MAX} characters.")

    return Skill(
        name=name, description=description, body=body, frontmatter=meta, files=files, source=source
    )


def render_skill_md(name: str, description: str, instructions: str) -> str:
    """A new SKILL.md with a correctly quoted front matter."""
    header = yaml.safe_dump(
        {"name": name, "description": description}, allow_unicode=True, sort_keys=False
    )
    return f"---\n{header}---\n\n{instructions.strip()}\n"


__all__ = [
    "SKILL_FILE",
    "Skill",
    "SkillFormatError",
    "check_name",
    "check_path",
    "parse",
    "render_skill_md",
    "split_frontmatter",
]
