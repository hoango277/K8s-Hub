"""Run a skill's script — in the sandbox chosen by SANDBOX_BACKEND.

Decision (29/09/2026): scripts run on the backend. Since 30/09/2026 the place
is configurable (app/modules/sandbox/): `local` keeps them on the backend,
`kubernetes` runs them in the sandbox pod's credential-less `runner`
container. Either way, whoever can edit a skill can run code there, so only
engineers and admins can create or edit skills.

Checked here, whatever the sandbox: only files inside scripts/, only known
interpreters (.py, .sh), a bounded number and size of arguments. The sandbox
adds the rest: no shell, a minimal environment, a temp dir, a time limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.modules.skills.parser import Skill, SkillFormatError, check_path

TIMEOUT_SECONDS = 60
MAX_ARGS = 20
MAX_ARG_LEN = 500
SCRIPT_SUFFIXES = (".py", ".sh")


@dataclass
class ScriptResult:
    ok: bool
    exit_code: int | None
    output: str
    duration_ms: int
    timed_out: bool = False


def check_script(skill: Skill, script: str, args: list[str]) -> str:
    path = check_path(script)
    if not path.startswith("scripts/"):
        raise SkillFormatError("Only files inside scripts/ can be run.")
    if path not in skill.files:
        raise SkillFormatError(f"{skill.name} has no file {path}.")
    if len(args) > MAX_ARGS or any(len(a) > MAX_ARG_LEN for a in args):
        raise SkillFormatError(f"At most {MAX_ARGS} arguments of {MAX_ARG_LEN} characters each.")
    if Path(path).suffix.lower() not in SCRIPT_SUFFIXES:
        raise SkillFormatError(f"Can't run {path}: only .py and .sh scripts are supported.")
    return path


async def run_script(skill: Skill, script: str, args: list[str]) -> ScriptResult:
    from app.modules.sandbox import SandboxError
    from app.modules.sandbox import run_script as sandbox_run

    path = check_script(skill, script, args)
    try:
        result = await sandbox_run(
            skill.files, path, args, time_limit=TIMEOUT_SECONDS, env={"K8S_HUB_SKILL": skill.name}
        )
    except SandboxError as exc:
        # Reported like a failed run (and logged as one), not as a bad request:
        # the script may be fine, the place it runs in isn't.
        return ScriptResult(ok=False, exit_code=None, output=str(exc), duration_ms=0)
    return ScriptResult(
        ok=result.ok,
        exit_code=result.exit_code,
        output=result.text(),
        duration_ms=result.duration_ms,
        timed_out=result.timed_out,
    )


__all__ = ["ScriptResult", "check_script", "run_script"]
