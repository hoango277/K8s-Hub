# Container exit codes

| Code | Meaning | Typical cause in Kubernetes |
|---|---|---|
| 0 | Normal exit | A job-like process in a Deployment; restartPolicy Always restarts it |
| 1 | Generic error | Uncaught exception, failed config parsing, missing env var |
| 2 | Invalid usage | Wrong command/args in the pod spec |
| 126 | Not executable | Entrypoint lacks execute permission |
| 127 | Command not found | Typo in `command`, binary missing from the image |
| 137 | SIGKILL (128+9) | **OOMKilled** if the reason says so; otherwise liveness probe kill or eviction |
| 139 | SIGSEGV (128+11) | Native crash (C extension, JNI, bad memory access) |
| 143 | SIGTERM (128+15) | Graceful stop: rollout, scale-down, drain |

Reading order that settles most cases:

1. The `reason` next to the code (`OOMKilled`, `Error`, `Completed`).
2. Events of the pod — who killed it and why.
3. The previous container's log — what the app said last.
