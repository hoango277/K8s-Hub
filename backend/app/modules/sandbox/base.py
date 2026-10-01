"""Run the two kinds of untrusted work K8s-Hub has, in one chosen place.

  - COMMANDS: a custom tool's CLI (kubectl, helm, argocd…) with arguments the
    model wrote. They need the cluster identity to do their job.
  - SCRIPTS: a skill's scripts/ file. They need no cluster access at all.

Two backends, chosen by SANDBOX_BACKEND (runtime-editable):

  local       a subprocess on the backend. Fine on a developer machine; the
              guard rails (no shell, minimal environment, temp dir, time
              limit) limit accidents but are NOT isolation.
  kubernetes  exec into the sandbox pod (deploy/sandbox/sandbox.yaml). Two
              containers: `runner` has no credentials and runs scripts, `cli`
              holds the sandbox ServiceAccount and runs commands. Neither can
              see the backend's API keys, database or JWT secret, and a script
              that goes wrong only damages a throwaway container.

Same idea as kubectl-ai's sandbox, with one difference: nothing here runs
through a shell. argv is always a list, so `; rm -rf /` in an argument is just
a strange argument.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import get_settings

MAX_OUTPUT = 10_000


class SandboxError(RuntimeError):
    """The sandbox itself failed (not the command). Message is user-facing."""


@dataclass
class ExecResult:
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def text(self, limit: int = MAX_OUTPUT) -> str:
        """stdout, then stderr under a marker; cut to `limit` characters."""
        out = self.stdout.rstrip()
        if self.stderr.strip():
            out += ("\n" if out else "") + "[stderr]\n" + self.stderr.rstrip()
        out = out or "(no output)"
        if len(out) > limit:
            out = out[:limit] + "\n… (output cut)"
        if self.timed_out:
            out += "\n(stopped: time limit reached)"
        return out


def backend_name() -> str:
    return get_settings().SANDBOX_BACKEND


async def run_command(argv: list[str], *, time_limit: int) -> ExecResult:
    """Run a CLI command (argv[0] is the program) with the cluster identity."""
    if not argv:
        raise SandboxError("Empty command.")
    if backend_name() == "kubernetes":
        from app.modules.sandbox import kubernetes

        return await kubernetes.run_command(argv, time_limit=time_limit)
    from app.modules.sandbox import local

    return await local.run_command(argv, time_limit=time_limit)


async def run_script(
    files: dict[str, bytes], script: str, args: list[str], *, time_limit: int, env: dict[str, str]
) -> ExecResult:
    """Copy `files` into a fresh directory and run `script` (a path among them)."""
    if backend_name() == "kubernetes":
        from app.modules.sandbox import kubernetes

        return await kubernetes.run_script(files, script, args, time_limit=time_limit, env=env)
    from app.modules.sandbox import local

    return await local.run_script(files, script, args, time_limit=time_limit, env=env)


__all__ = ["ExecResult", "SandboxError", "backend_name", "run_command", "run_script"]
