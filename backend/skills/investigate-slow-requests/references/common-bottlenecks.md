# Common bottlenecks and what points to them

| Pattern in the trace | Confirm with | Usual cause |
|---|---|---|
| One DB/client span takes most of the time | logs of that service ("slow query", "timeout") | missing index, lock contention, DB overloaded |
| Many short sequential calls to the same service | the span list itself | N+1 calls; batch them |
| A service's own self-time is high | `pod_metrics(..., "throttling")` | CPU limit too low → throttling |
| Gap between parent and child spans | — | queueing: thread/connection pool exhausted |
| Error span with "timeout" at the deepest level | the callee's metrics and logs | the callee is down or saturated; callers only propagate |
| Latency grows over hours, then resets | `pod_metrics(..., "memory")`, restarts | memory leak → GC pressure → OOM restart |
