"""SANDBOX_BACKEND=kubernetes: exec into the sandbox pod (deploy/sandbox/sandbox.yaml).

The pod is created by that manifest, not by the backend: its RBAC is then
written down and reviewed once, and the backend itself needs only `pods/exec`
in the sandbox namespace — not the right to create pods anywhere.

Two containers, two jobs:
  - `cli`    has the sandbox ServiceAccount token and runs custom-tool
             commands (kubectl, helm…);
  - `runner` has NO token (not even mounted) and runs skill scripts, so a
             script can't touch the cluster whatever it contains.

Why the exec protocol is read by hand: kubernetes_asyncio's ready-made helper
merges stdout and stderr and throws the exit code away; both matter here.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.integrations.k8s import client as k8s
from app.modules.sandbox.base import ExecResult, SandboxError

CLI_CONTAINER = "cli"
RUNNER_CONTAINER = "runner"
# exec(2)'s single-argument limit is 128 KiB; stay well under it.
MAX_SCRIPT_PAYLOAD = 100_000
# Exit code both `timeout` and the script bootstrap use for "time limit hit".
TIMEOUT_EXIT = 124

STDOUT, STDERR, ERROR = 1, 2, 3

# Runs inside `runner`: unpack the skill into a temp dir, run the script with
# a minimal environment and a time limit, forward its output and exit code.
_BOOTSTRAP = """\
import base64, json, os, shutil, subprocess, sys, tempfile
p = json.loads(base64.b64decode(sys.argv[1]))
d = tempfile.mkdtemp(prefix="skill-")
try:
    for rel, data in p["files"].items():
        t = os.path.join(d, rel)
        os.makedirs(os.path.dirname(t), exist_ok=True)
        with open(t, "wb") as f:
            f.write(base64.b64decode(data))
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": d,
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    env.update(p["env"])
    cmd = [*p["interp"], os.path.join(d, p["script"]), *p["args"]]
    try:
        r = subprocess.run(cmd, cwd=d, env=env, capture_output=True,
                           timeout=p["timeout"], stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        sys.stdout.buffer.write(e.stdout or b"")
        sys.stderr.buffer.write(e.stderr or b"")
        sys.exit(124)
    sys.stdout.buffer.write(r.stdout)
    sys.stderr.buffer.write(r.stderr)
    sys.exit(r.returncode)
finally:
    shutil.rmtree(d, ignore_errors=True)
"""

_pod_cache: tuple[str, float] | None = None
_POD_CACHE_SECONDS = 30


async def _sandbox_pod() -> str:
    """Name of a running, ready sandbox pod. Cached briefly: one list per call
    would double the latency of every command."""
    global _pod_cache
    if _pod_cache and time.monotonic() - _pod_cache[1] < _POD_CACHE_SECONDS:
        return _pod_cache[0]
    settings = get_settings()
    try:
        pods = await k8s.list_pods(settings.SANDBOX_NAMESPACE, settings.SANDBOX_SELECTOR)
    except k8s.K8sError as exc:
        raise SandboxError(f"Can't find the sandbox pod: {exc}") from exc
    for pod in pods:
        statuses = (pod.status and pod.status.container_statuses) or []
        if (
            pod.status.phase == "Running"
            and not pod.metadata.deletion_timestamp
            and statuses
            and all(s.ready for s in statuses)
        ):
            _pod_cache = (pod.metadata.name, time.monotonic())
            return pod.metadata.name
    raise SandboxError(
        f"No ready sandbox pod in namespace {settings.SANDBOX_NAMESPACE} "
        f"(selector {settings.SANDBOX_SELECTOR}). Apply deploy/sandbox/sandbox.yaml, "
        "or set SANDBOX_BACKEND=local."
    )


def _exit_code(error_payload: bytes) -> int | None:
    """Channel 3 carries a Status object: Success, or Failure with the exit code."""
    try:
        status = json.loads(error_payload)
    except ValueError:
        return None
    if status.get("status") == "Success":
        return 0
    for cause in (status.get("details") or {}).get("causes") or []:
        if cause.get("reason") == "ExitCode":
            try:
                return int(cause.get("message"))
            except (TypeError, ValueError):
                return None
    return None


async def _exec(container: str, argv: list[str], *, time_limit: int) -> ExecResult:
    from kubernetes_asyncio import client

    pod = await _sandbox_pod()
    namespace = get_settings().SANDBOX_NAMESPACE
    stdout, stderr = bytearray(), bytearray()
    code: int | None = None
    error_text = ""
    started = time.perf_counter()
    try:
        async with k8s.ws_api_client() as ws_api:
            ctx: Any = await client.CoreV1Api(ws_api).connect_get_namespaced_pod_exec(
                pod,
                namespace,
                container=container,
                command=argv,
                stdin=False,
                stdout=True,
                stderr=True,
                tty=False,
                _preload_content=False,
            )
            # The in-pod `timeout` stops the program; this outer limit only
            # guards against a hung connection.
            async with asyncio.timeout(time_limit + 15):
                async with ctx as ws:
                    async for msg in ws:
                        data = msg.data if isinstance(msg.data, bytes) else b""
                        if not data:
                            continue
                        channel, payload = data[0], data[1:]
                        if channel == STDOUT:
                            stdout += payload
                        elif channel == STDERR:
                            stderr += payload
                        elif channel == ERROR:
                            code = _exit_code(payload)
                            if code is None:
                                error_text = payload.decode("utf-8", "replace")
    except TimeoutError:
        return ExecResult(
            exit_code=None,
            stdout=stdout.decode("utf-8", "replace"),
            stderr=stderr.decode("utf-8", "replace"),
            duration_ms=int((time.perf_counter() - started) * 1000),
            timed_out=True,
        )
    except k8s.K8sError as exc:
        raise SandboxError(str(exc)) from exc
    except Exception as exc:
        global _pod_cache
        _pod_cache = None  # the pod may have been replaced; look it up again next time
        raise SandboxError(
            f"Exec into the sandbox pod failed: {type(exc).__name__}: {exc}"
        ) from exc

    if code is None and error_text:
        # e.g. "executable file not found in $PATH"
        raise SandboxError(f"The sandbox could not run {argv[0]}: {error_text[:300]}")
    return ExecResult(
        exit_code=code,
        stdout=stdout.decode("utf-8", "replace"),
        stderr=stderr.decode("utf-8", "replace"),
        duration_ms=int((time.perf_counter() - started) * 1000),
        timed_out=code == TIMEOUT_EXIT,
    )


async def run_command(argv: list[str], *, time_limit: int) -> ExecResult:
    # coreutils `timeout`: TERM at the limit, KILL 5 s later if ignored.
    return await _exec(
        CLI_CONTAINER, ["timeout", "-k", "5", str(time_limit), *argv], time_limit=time_limit
    )


def interpreter(script: str) -> list[str]:
    suffix = Path(script).suffix.lower()
    if suffix == ".py":
        return ["python3"]
    if suffix == ".sh":
        return ["bash"]
    raise SandboxError(f"Can't run {script}: only .py and .sh scripts are supported.")


async def run_script(
    files: dict[str, bytes], script: str, args: list[str], *, time_limit: int, env: dict[str, str]
) -> ExecResult:
    payload = base64.b64encode(
        json.dumps(
            {
                "files": {k: base64.b64encode(v).decode() for k, v in files.items()},
                "script": script,
                "interp": interpreter(script),
                "args": args,
                "timeout": time_limit,
                "env": env,
            }
        ).encode()
    ).decode()
    if len(payload) > MAX_SCRIPT_PAYLOAD:
        raise SandboxError(
            "This skill is too large to send to the sandbox "
            f"(limit about {MAX_SCRIPT_PAYLOAD * 3 // 4 // 1000} KB of files)."
        )
    return await _exec(
        RUNNER_CONTAINER, ["python3", "-c", _BOOTSTRAP, payload], time_limit=time_limit
    )


__all__ = ["run_command", "run_script"]
