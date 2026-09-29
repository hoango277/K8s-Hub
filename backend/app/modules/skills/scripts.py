"""Run a skill's script ON THE BACKEND — a deliberate choice, with known risk.

Decision (29/09/2026): scripts run directly on the K8s-Hub backend, not in a
sandbox. Consequence: whoever can edit a skill can run code on this server.
That is why only engineers and admins can create or edit skills. The guard
rails below limit accidents; they are NOT a sandbox:

  - no shell: argv is passed as a list, so arguments can't inject commands;
  - a minimal environment: API keys, DATABASE_URL, JWT_SECRET and every other
    variable of this process are NOT passed to the script (it can still read
    files the backend can read — this is not isolation);
  - the skill folder is copied to a fresh temporary directory, which is the
    working directory, and deleted afterwards;
  - a time limit and an output cap;
  - only known interpreters (.py with this venv's Python, .sh with bash).

Runs happen in a worker thread: asyncio subprocesses are not available under
every Windows event loop uvicorn may pick.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from app.modules.skills.parser import Skill, SkillFormatError, check_path

TIMEOUT_SECONDS = 60
MAX_OUTPUT = 10_000
MAX_ARGS = 20
MAX_ARG_LEN = 500

# Variables a script genuinely needs to start; everything else is dropped.
_KEEP_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "TZ")


@dataclass
class ScriptResult:
    ok: bool
    exit_code: int | None
    output: str
    duration_ms: int
    timed_out: bool = False


def _interpreter(path: str) -> list[str]:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return [sys.executable]
    if suffix == ".sh":
        bash = shutil.which("bash")
        if bash:
            return [bash]
        raise SkillFormatError("Shell scripts need bash, which isn't installed on this server.")
    raise SkillFormatError(f"Can't run {path}: only .py and .sh scripts are supported.")


def _env(skill: Skill) -> dict[str, str]:
    env = {k: os.environ[k] for k in _KEEP_ENV if k in os.environ}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", K8S_HUB_SKILL=skill.name)
    return env


def check_script(skill: Skill, script: str, args: list[str]) -> str:
    path = check_path(script)
    if not path.startswith("scripts/"):
        raise SkillFormatError("Only files inside scripts/ can be run.")
    if path not in skill.files:
        raise SkillFormatError(f"{skill.name} has no file {path}.")
    if len(args) > MAX_ARGS or any(len(a) > MAX_ARG_LEN for a in args):
        raise SkillFormatError(f"At most {MAX_ARGS} arguments of {MAX_ARG_LEN} characters each.")
    _interpreter(path)
    return path


def _run_blocking(skill: Skill, path: str, args: list[str]) -> ScriptResult:
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix=f"skill-{skill.name}-") as tmp:
        root = Path(tmp)
        for rel, content in skill.files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        cmd = [*_interpreter(path), str(root / path), *args]
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell; see module docstring
                cmd,
                cwd=root,
                env=_env(skill),
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired as exc:
            partial = (exc.stdout or b"") + (exc.stderr or b"")
            return ScriptResult(
                ok=False,
                exit_code=None,
                output=_clip(partial.decode("utf-8", "replace"))
                + f"\n(stopped after {TIMEOUT_SECONDS} s)",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    text = out + (f"\n[stderr]\n{err}" if err.strip() else "")
    return ScriptResult(
        ok=proc.returncode == 0,
        exit_code=proc.returncode,
        output=_clip(text.strip() or "(no output)"),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _clip(text: str) -> str:
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + "\n… (output cut)"


async def run_script(skill: Skill, script: str, args: list[str]) -> ScriptResult:
    path = check_script(skill, script, args)
    return await asyncio.to_thread(_run_blocking, skill, path, args)


__all__ = ["ScriptResult", "check_script", "run_script"]
