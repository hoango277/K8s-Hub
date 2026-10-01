---
name: diagnose-crashloop
description: Find out why a pod keeps crashing or restarting — CrashLoopBackOff, OOMKilled, non-zero exit codes, failing liveness probes. Use when a user reports a pod restarting, an app that keeps crashing, or asks "why is X in CrashLoopBackOff".
---

# Diagnose a crash-looping pod

Work from evidence, in this order. Never guess a cause the tools didn't show.

## 1. Find the pod

- If the user named a namespace but not a pod: `list_pods(namespace)`. Pods with
  problems are listed first; pick the one in CrashLoopBackOff or with the most restarts.
- If they named a deployment: `list_pods(namespace, label_selector="app=<name>")`
  or use the deployment name as the pod prefix in later steps.

## 2. Read how it died

Call `describe_pod(namespace, name)` and note, for the failing container:

- `last exit: <reason> exit <code>` — the most important line;
- `now: waiting CrashLoopBackOff` — Kubernetes is waiting before the next restart;
- the recent events (probe failures, OOM kills, image or config errors);
- the memory `limits`.

## 3. Interpret the exit code

Run `run_skill_script(name="diagnose-crashloop", script="scripts/explain_exit_code.py", arguments=[<code>, <reason>])`
— for example `["137", "OOMKilled"]`. It prints what the code means and what to check
next. For the full table: `read_skill_file(name="diagnose-crashloop", path="references/exit-codes.md")`.

## 4. Follow the branch that matches

| What step 2 showed | Next tool | What to look for |
|---|---|---|
| `OOMKilled` (exit 137) | `pod_metrics(namespace, <prefix>, "memory", 60)` | peak vs limit; a steady climb means a leak, a spike means a burst |
| exit 1 / 2 / other app code | `get_pod_logs(namespace, name, previous=True)` | the last error before the crash — the CURRENT instance has just started |
| the same, but restarts over hours | `search_logs(namespace, pod=<prefix>, errors_only=True, since_minutes=360)` | whether it is always the same error |
| `Liveness probe failed` in events | `read_skill_file(..., path="references/probe-failures.md")` | probe too strict vs app really hung |
| `CreateContainerConfigError` | events in `describe_pod` | a missing Secret or ConfigMap key |
| exit 137 WITHOUT OOMKilled | events | killed by a failing liveness probe or by eviction |

## 5. Answer

Reply in this shape, short:

1. **What is happening** — one sentence.
2. **Evidence** — quote the exact lines (exit code, event, log line, metric) you relied on.
3. **Most likely cause** — and how sure you are, based on how much evidence agrees.
4. **Suggested fix** — describe it (e.g. "raise the memory limit from 256Mi to 512Mi").
   Do NOT claim it is applied: changes to the cluster go through the approval flow.
