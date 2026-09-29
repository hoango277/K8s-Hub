"""Tests for Agent Skills: the SKILL.md format, zip import/export, scripts, and the prompt."""

from __future__ import annotations

import io
import os
import zipfile

import pytest

from app.modules.skills import agent_tools
from app.modules.skills.parser import SkillFormatError, parse, render_skill_md
from app.modules.skills.scripts import run_script
from app.modules.skills.store import SkillStore, load_builtin
from app.services import skill_service


def md(name="check-thing", description="Checks a thing. Use when asked about things.", body="Do it."):
    return render_skill_md(name, description, body).encode()


# --------------------------------------------------------------------------
# SKILL.md format
# --------------------------------------------------------------------------


def test_minimal_skill_parses():
    s = parse({"SKILL.md": md()}, source="custom")
    assert (s.name, s.description, s.body) == (
        "check-thing",
        "Checks a thing. Use when asked about things.",
        "Do it.",
    )


@pytest.mark.parametrize(
    "text, message",
    [
        (b"no front matter", "must start with a YAML front matter"),
        (b"---\nname: x\n", "not closed"),
        (b"---\ndescription: d\n---\nbody", "name must be"),
        (b"---\nname: ok-name\n---\nbody", "needs a description"),
        (b"---\nname: Bad_Name\ndescription: d\n---\n", "name must be"),
        (b"---\nname: my-claude-helper\ndescription: d\n---\n", "reserved words"),
        (b"---\n- a list\n---\n", "must be a mapping"),
    ],
)
def test_invalid_skill_md_is_rejected(text, message):
    with pytest.raises(SkillFormatError, match=message):
        parse({"SKILL.md": text}, source="custom")


def test_name_must_match_the_folder():
    with pytest.raises(SkillFormatError, match="must match the folder name"):
        parse({"SKILL.md": md()}, source="custom", folder_name="other-name")


@pytest.mark.parametrize("path", ["../escape.py", "/etc/passwd", "C:/x.py", "scripts/../../x", ""])
def test_paths_outside_the_skill_are_rejected(path):
    with pytest.raises(SkillFormatError):
        parse({"SKILL.md": md(), path: b"x"}, source="custom")


def test_builtin_skills_in_the_repo_are_valid():
    """A broken SKILL.md in backend/skills/ would be skipped silently at startup."""
    names = {s.name for s in load_builtin()}
    assert {"diagnose-crashloop", "investigate-slow-requests", "namespace-health-check"} <= names


# --------------------------------------------------------------------------
# Zip import / export
# --------------------------------------------------------------------------


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def test_export_then_import_is_lossless():
    skill = parse(
        {"SKILL.md": md(), "scripts/run.py": b"print(1)", "assets/logo.png": b"\x89PNG\x00\x01"},
        source="custom",
    )
    files, folder = skill_service._read_zip(skill_service.export_zip(skill))
    assert folder == "check-thing"
    assert files == skill.files


def test_zip_with_skill_md_at_the_root_is_accepted():
    files, folder = skill_service._read_zip(_zip({"SKILL.md": md(), "references/a.md": b"a"}))
    assert folder is None and set(files) == {"SKILL.md", "references/a.md"}


def test_zip_with_two_skills_is_rejected():
    data = _zip({"a/SKILL.md": md("a-skill"), "b/SKILL.md": md("b-skill")})
    with pytest.raises(skill_service.SkillServiceError, match="one skill"):
        skill_service._read_zip(data)


# --------------------------------------------------------------------------
# Scripts run on the backend — with a stripped environment
# --------------------------------------------------------------------------


async def test_script_gets_arguments_and_no_secrets(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "must-not-leak")
    monkeypatch.setenv("GROQ_API_KEY", "must-not-leak")
    code = b"import os, sys\nprint(sys.argv[1:], os.environ.get('JWT_SECRET'), os.environ.get('GROQ_API_KEY'))"
    skill = parse({"SKILL.md": md(), "scripts/show.py": code}, source="custom")
    result = await run_script(skill, "scripts/show.py", ["a b", "--x"])
    assert result.ok
    assert result.output == "['a b', '--x'] None None"
    assert os.environ["JWT_SECRET"] == "must-not-leak"  # the backend's own env is untouched


async def test_failing_script_reports_its_exit_code():
    skill = parse({"SKILL.md": md(), "scripts/fail.py": b"import sys; print('boom'); sys.exit(3)"}, source="custom")
    result = await run_script(skill, "scripts/fail.py", [])
    assert (result.ok, result.exit_code) == (False, 3)
    assert "boom" in result.output


async def test_only_known_interpreters_run():
    skill = parse({"SKILL.md": md(), "scripts/tool.exe": b"MZ"}, source="custom")
    with pytest.raises(SkillFormatError, match="only .py and .sh"):
        await run_script(skill, "scripts/tool.exe", [])


# --------------------------------------------------------------------------
# Progressive disclosure: names in the prompt, bodies on demand
# --------------------------------------------------------------------------


@pytest.fixture
def one_skill(monkeypatch):
    s = SkillStore()
    s.load([parse({"SKILL.md": md(body="Step 1. Do the thing."), "references/r.md": b"ref"}, source="custom")], {})
    monkeypatch.setattr(agent_tools, "store", s)
    return s


def test_prompt_lists_names_and_descriptions_only(one_skill):
    prompt = agent_tools.skills_prompt()
    assert "- check-thing: Checks a thing." in prompt
    assert "Step 1" not in prompt  # the body is only loaded on demand


def test_load_skill_returns_body_and_file_list(one_skill):
    text = agent_tools.load_skill.invoke({"name": "check-thing"})
    assert "Step 1. Do the thing." in text and "references/r.md" in text


def test_disabled_skill_is_invisible(one_skill):
    one_skill.set_enabled("check-thing", False)
    assert agent_tools.skills_prompt() == ""
    assert agent_tools.skill_tools() == []
    assert "No enabled skill" in agent_tools.load_skill.invoke({"name": "check-thing"})
