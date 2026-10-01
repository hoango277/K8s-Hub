"""SANDBOX_BACKEND=local: a subprocess on the backend itself.

Guard rails, not isolation (see base.py): no shell, a minimal environment
(API keys, DATABASE_URL, JWT_SECRET are never passed on), a fresh temporary
working directory, a time limit and an output cap.

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
from pathlib import Path

from app.modules.sandbox.base import ExecResult, SandboxError

# What any program needs to start on Windows or Linux.
_BASE_ENV = ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "LANG", "TZ")
# Commands also need to find their own config — kubectl its kubeconfig, helm its
# cache. These are paths, not secrets; the files they point to are the
# identity the command runs with (on a dev machine: yours).
_COMMAND_ENV = (
    *_BASE_ENV,
    "HOME",
    "USERPROFILE",
    "APPDATA",
    "LOCALAPPDATA",
    "HOMEDRIVE",
    "HOMEPATH",
    "KUBECONFIG",
)


def _env(keep: tuple[str, ...], extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.update(extra or {})
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> ExecResult:
    started = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 - argv list, never a shell; see module docstring
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        return ExecResult(
            exit_code=None,
            stdout=(exc.stdout or b"").decode("utf-8", "replace"),
            stderr=(exc.stderr or b"").decode("utf-8", "replace"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=True,
        )
    except OSError as exc:
        raise SandboxError(f"Could not start {argv[0]}: {exc}") from exc
    return ExecResult(
        exit_code=proc.returncode,
        stdout=proc.stdout.decode("utf-8", "replace"),
        stderr=proc.stderr.decode("utf-8", "replace"),
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def _command_blocking(argv: list[str], timeout: int) -> ExecResult:
    program = shutil.which(argv[0])
    if program is None:
        raise SandboxError(f"{argv[0]} is not installed on the backend machine.")
    with tempfile.TemporaryDirectory(prefix="k8s-hub-cmd-") as tmp:
        return _run(
            [program, *argv[1:]], cwd=Path(tmp), env=_env(_COMMAND_ENV), timeout=timeout
        )


def interpreter(script: str) -> list[str]:
    suffix = Path(script).suffix.lower()
    if suffix == ".py":
        return [sys.executable]
    if suffix == ".sh":
        bash = shutil.which("bash")
        if bash:
            return [bash]
        raise SandboxError("Shell scripts need bash, which isn't installed on the backend.")
    raise SandboxError(f"Can't run {script}: only .py and .sh scripts are supported.")


def _script_blocking(
    files: dict[str, bytes], script: str, args: list[str], timeout: int, env: dict[str, str]
) -> ExecResult:
    with tempfile.TemporaryDirectory(prefix="k8s-hub-skill-") as tmp:
        root = Path(tmp)
        for rel, content in files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        argv = [*interpreter(script), str(root / script), *args]
        return _run(argv, cwd=root, env=_env(_BASE_ENV, env), timeout=timeout)


async def run_command(argv: list[str], *, time_limit: int) -> ExecResult:
    return await asyncio.to_thread(_command_blocking, argv, time_limit)


async def run_script(
    files: dict[str, bytes], script: str, args: list[str], *, time_limit: int, env: dict[str, str]
) -> ExecResult:
    return await asyncio.to_thread(_script_blocking, files, script, args, time_limit, env)


__all__ = ["interpreter", "run_command", "run_script"]
