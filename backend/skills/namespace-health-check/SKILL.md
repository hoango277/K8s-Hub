---
name: namespace-health-check
description: Give a quick health report of one namespace — unhealthy pods, deployments not fully ready, recent warning events, and containers close to their resource limits. Use when a user asks "is everything OK in X", "check namespace X", or wants a status overview.
---

# Namespace health check

Collect, then report in the fixed format of `assets/report-template.md`.

## Collect

1. `list_deployments(namespace)` — any `ready` below desired, or a rollout condition not True.
2. `list_pods(namespace)` — pods with problems are listed first; note restarts.
3. `list_events(namespace, warnings_only=True, since_minutes=60)` — group repeated warnings.
4. For each deployment with problems (at most three):
   `pod_metrics(namespace, <deployment>, "memory", 60)` — flag peaks above 80 % of the limit.

Stop early and say so if a tool reports that Kubernetes access isn't configured.
Call each tool once per object; "no data" goes in the report as such.

## Report

Read `assets/report-template.md` and fill it in. Keep the "All good" section short;
spend the words on what needs attention. If something needs a deeper look, name the
skill for it (e.g. `diagnose-crashloop` for a crash-looping pod).
