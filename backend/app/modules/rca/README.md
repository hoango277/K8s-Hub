# Module: Root Cause Analysis (Groot-style event graph)

Plan and rationale: `docs/ke-hoach/rca-groot.md`. What runs today: `docs/hien-trang-codebase.md` §3.12.

```
snapshot → topology → event history → detectors → causal graph → ranking → (LLM check + report)
```

| File | Responsibility |
|---|---|
| `model.py` | Entity, Event, Evidence (≤300 chars), CausalEdge, Hypothesis; 33 event types with root-cause priors |
| `snapshot.py` | One parallel read of the WHOLE cluster: 13 kinds + nodes, Secret metadata, Argo CD apps |
| `topology.py` | Cluster-wide dependency graph: Kubernetes structure + "calls" from config, metrics, traces, logs, annotation (each edge keeps its sources); scope expansion |
| `events_store.py` | Kubernetes events: API (≤1 h) + Loki history (`job="kubernetes-events"`, written by Alloy) |
| `detectors/` | pods, workloads, nodes, changes (+ControllerRevision, Argo CD, Helm, Secret metadata), metrics (change-point, seasonal, leak), logs (Drain3, 6 h baseline, host mentions), traces, dependencies (Beyla client metrics) |
| `rules.py` | 112 causal rules as data; relations may chain (`owner+callee+pods`) for failures that travel along dependencies |
| `causality.py` | Builds the event graph backwards from symptoms; no rule, no edge |
| `ranking.py` | Personalized PageRank on the reversed graph × type prior, root bonus, earlier wins ties |
| `pipeline.py` | `analyze()` (deterministic, no DB) and stored runs (`rca_runs`), step progress |
| `remediation.py` | Fix candidates derived from event facts (rollback image, scale back) or advice |
| `report.py` | LLM verification with a fixed read-only tool budget, JSON report, deterministic validator |
| `triggers.py` | Alertmanager webhook: parse alerts, dedup by fingerprint, start runs |
| `scanner.py` | Periodic scan of RCA_SCAN_NAMESPACES (empty = whole cluster); diagnoses each new critical symptom once |
| `learning.py` | Feedback → per-rule / per-type factors (`rca_weights`), smoothed and clamped |

Entry points: `api/v1/rca.py` (REST + SSE), `tools/builtin/rca.py` (`diagnose_incident` chat tool).
