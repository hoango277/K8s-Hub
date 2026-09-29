"""How the chat agent uses skills — progressive disclosure, as in the Agent Skills standard.

  Level 1  `skills_prompt()`   name + description of every enabled skill go in the
                               system prompt (a line each), so the model knows what exists.
  Level 2  `load_skill`        the model loads SKILL.md's instructions when a request matches.
  Level 3  `read_skill_file`   it reads a reference/asset only when the instructions point to it;
           `run_skill_script`  or runs one of the skill's scripts.

Only level 1 costs tokens on every turn; a skill's full text enters the context
only when it is actually used.
"""

from __future__ import annotations

import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool

from app.modules.skills.parser import SKILL_FILE, SkillFormatError
from app.modules.skills.scripts import run_script
from app.modules.skills.store import store

logger = logging.getLogger(__name__)

MAX_FILE_CHARS = 30_000


def skills_prompt() -> str:
    """Level 1: the lines appended to the system prompt. Empty when no skill is enabled."""
    skills = store.enabled()
    if not skills:
        return ""
    lines = [
        "AVAILABLE SKILLS",
        "Skills are step-by-step procedures for specific tasks. When a request matches a "
        "skill's description, call load_skill with its name FIRST and follow its "
        "instructions, instead of improvising.",
    ]
    lines += [f"- {s.name}: {s.description}" for s in skills]
    return "\n".join(lines)


def _enabled_skill(name: str):
    skill = store.get(name)
    if skill is None or not store.is_enabled(name):
        available = ", ".join(s.name for s in store.enabled()) or "(none)"
        raise SkillFormatError(f"No enabled skill named {name!r}. Available: {available}.")
    return skill


@tool(parse_docstring=True)
def load_skill(name: str) -> str:
    """Load a skill's instructions (its SKILL.md). Call this before doing a task a skill covers.

    Args:
        name: the skill name from the AVAILABLE SKILLS list.
    """
    try:
        skill = _enabled_skill(name)
    except SkillFormatError as exc:
        return str(exc)
    lines = [f"# Skill: {skill.name}", "", skill.body]
    others = skill.other_files()
    if others:
        lines += [
            "",
            "Files in this skill (read_skill_file to read, run_skill_script for scripts/):",
        ]
        lines += [f"- {p} ({len(skill.files[p]):,} bytes)" for p in others]
    return "\n".join(lines)


@tool(parse_docstring=True)
def read_skill_file(name: str, path: str) -> str:
    """Read a file of a skill, e.g. a document in references/ or a template in assets/.

    Args:
        name: the skill name.
        path: file path inside the skill, e.g. "references/exit-codes.md".
    """
    try:
        skill = _enabled_skill(name)
    except SkillFormatError as exc:
        return str(exc)
    content = skill.files.get(path.replace("\\", "/").lstrip("./"))
    if content is None:
        return f"{name} has no file {path!r}. Files: {', '.join(skill.other_files()) or '(none)'}."
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return f"{path} is a binary file ({len(content):,} bytes) and can't be shown as text."
    if path == SKILL_FILE:
        return load_skill.invoke({"name": name})
    return text if len(text) <= MAX_FILE_CHARS else text[:MAX_FILE_CHARS] + "\n… (file cut)"


@tool(parse_docstring=True)
async def run_skill_script(
    name: str, script: str, config: RunnableConfig, arguments: list[str] | None = None
) -> str:
    """Run one of a skill's scripts (a file in its scripts/ folder) and return its output.

    Only run scripts that load_skill listed for this skill and that its instructions tell
    you to run, with the arguments they describe. Never guess a script name.

    Args:
        name: the skill name.
        script: path of the script inside the skill, e.g. "scripts/explain_exit_code.py".
        arguments: command-line arguments for the script.
    """
    from app.services import skill_service

    try:
        skill = _enabled_skill(name)
        result = await run_script(skill, script, list(arguments or []))
    except SkillFormatError as exc:
        return str(exc)

    meta = (config or {}).get("metadata") or {}
    await skill_service.log_run_detached(
        skill=name,
        script=script,
        args=list(arguments or []),
        result=result,
        actor_email=str(meta.get("user") or "assistant"),
        trigger="chat",
    )
    status = (
        "exit 0" if result.ok else ("timed out" if result.timed_out else f"exit {result.exit_code}")
    )
    return f"[{status}, {result.duration_ms} ms]\n{result.output}"


def skill_tools() -> list[BaseTool]:
    """The three skill tools — only when at least one skill is enabled."""
    return [load_skill, read_skill_file, run_skill_script] if store.enabled() else []


__all__ = ["load_skill", "read_skill_file", "run_skill_script", "skill_tools", "skills_prompt"]
