---
name: investigate-slow-requests
description: Find where time goes when requests to an app on the cluster are slow or failing with 5xx — using traces first, then metrics and logs to confirm. Use when a user reports latency, timeouts, or HTTP 500s from a service.
---

# Investigate slow or failing requests

Traces say WHERE the time or the error is; metrics and logs say WHY.

## 1. Find the service

`list_traced_services()` — map the user's words ("checkout", "the API") to an exact
service name. If Tempo has no traces, say so and skip to step 4 with metrics and logs.

## 2. Find representative traces

- Errors: `search_traces(service=<name>, only_errors=True, since_minutes=30)`
- Slowness: `search_traces(service=<name>, min_duration_ms=<threshold>, since_minutes=30)`
  — pick a threshold clearly above normal (e.g. 1000 ms for a web request).

## 3. Explain one or two traces

`get_trace(trace_id)` for the newest matching trace. Read:

- **Slowest path** — the chain the request waited on; the deepest slow span is the bottleneck.
- **Failed spans** — the FIRST (deepest) failure is usually the cause; outer ones propagate it.
- **Time per service** — where the time actually went.

If two traces disagree, look at a third before concluding.

## 4. Confirm with the owning workload

For the service identified as the bottleneck (map it to its namespace and pod prefix):

- `pod_metrics(namespace, <prefix>, "cpu", 60)` and `"throttling"` — CPU starvation?
- `pod_metrics(namespace, <prefix>, "memory", 60)` — near its limit?
- `search_logs(namespace, pod=<prefix>, errors_only=True, since_minutes=60)` — timeouts,
  connection errors, slow-query warnings.

Call each of these at most once. "No data" is a finding, not a failure: note it
("no metrics or error logs for this workload") and move on — don't retry with other
metrics or wider windows hoping for something to appear.

Patterns and what each points to: `read_skill_file(name="investigate-slow-requests", path="references/common-bottlenecks.md")`.

## 5. Answer

1. **Where** — the span/service that takes the time or fails first, with its duration.
2. **Why** — the metric or log line that explains it.
3. **Suggested fix** — described, not applied.
