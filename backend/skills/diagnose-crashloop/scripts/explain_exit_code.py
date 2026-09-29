"""Explain a container exit code, optionally with the reason Kubernetes reported.

Usage: python explain_exit_code.py <exit_code> [reason]
  e.g. python explain_exit_code.py 137 OOMKilled

Signal numbers are Linux's (containers run on Linux), written out here rather
than read from the `signal` module, which lacks SIGKILL on Windows hosts.
"""

from __future__ import annotations

import sys

KNOWN = {
    0: ("Exited normally.",
        "If it still restarts, check restartPolicy and whether the process should run forever."),
    1: ("Generic application error.",
        "Read the previous container's log: get_pod_logs(..., previous=True)."),
    2: ("Invalid usage / arguments.", "Check the container command and args in the pod spec."),
    126: ("Command found but not executable.", "Wrong file permissions on the entrypoint."),
    127: ("Command not found.", "Typo in the command, or the binary is missing from the image."),
}

# Linux signal number -> (name, what it usually means for a container)
SIGNALS = {
    6: ("SIGABRT", "Aborted — an assertion or unhandled fatal error in the runtime."),
    9: ("SIGKILL", "Killed. With reason OOMKilled it hit its memory limit; otherwise a failing "
        "liveness probe, an eviction, or a manual kill."),
    11: ("SIGSEGV", "Segmentation fault — a crash in native code."),
    15: ("SIGTERM", "Stopped gracefully — rollout, scale down, node drain, or a liveness restart."),
}


def explain(code: int, reason: str | None) -> str:
    lines = [f"Exit code {code}" + (f" (reason: {reason})" if reason else "") + ":"]
    if reason == "OOMKilled":
        lines.append("- The container used more memory than its limit and the kernel killed it.")
        lines.append("- Next: pod_metrics(namespace, <pod prefix>, 'memory', 60) — peak vs limit.")
        return "\n".join(lines)
    if code in KNOWN:
        meaning, hint = KNOWN[code]
        lines += [f"- {meaning}", f"- Next: {hint}"]
    elif 128 < code < 160:
        number = code - 128
        name, meaning = SIGNALS.get(number, (f"signal {number}", "Terminated by a signal."))
        lines += [f"- Terminated by {name} ({code} = 128 + {number}).", f"- {meaning}"]
        if number == 9:
            lines.append("- Next: check the pod events for 'Liveness probe failed' or 'Evicted'.")
    else:
        lines.append("- Application-specific code. Read the previous container's log.")
    return "\n".join(lines)


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].lstrip("-").isdigit():
        print(__doc__)
        return 2
    print(explain(int(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
