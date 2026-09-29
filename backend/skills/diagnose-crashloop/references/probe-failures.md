# Liveness and readiness probe failures

- **Liveness probe failed** → Kubernetes RESTARTS the container. Repeated, it looks
  exactly like a crash loop, with exit 137 or 143 and no OOMKilled.
- **Readiness probe failed** → the pod is removed from Service endpoints but NOT
  restarted. Users see errors; restarts stay at 0.

Tell the two situations apart:

| Signal | Probe too strict | App really hung |
|---|---|---|
| Fails right after start | `initialDelaySeconds` too short for a slow start | — |
| Fails under load only | `timeoutSeconds` too short | CPU throttling (`pod_metrics(..., "throttling")`) |
| Log stops before the kill | — | deadlock or blocked event loop |

Suggest, don't apply: a longer `initialDelaySeconds` or a `startupProbe` for slow
starts; a larger `timeoutSeconds`/`failureThreshold` for load spikes; fixing the
hang when the log shows the app stopped responding.
