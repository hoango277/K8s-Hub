# Module: Observability (of the LLM / Agent)

> **This module's scope = monitoring the AI itself**, not monitoring the K8s cluster.
>
> - Monitoring the target K8s cluster (evidence source for RCA) → `app/integrations/prometheus`, `app/integrations/loki`
> - Monitoring the health of the K8s-Hub app itself → `app/core/telemetry.py`

It answers two questions:

1. **What did the LLM do?** — which prompt, which model, which tools it called, how many tokens/how much money, how long it took. → Langfuse.
2. **What did the LLM affect?** — which resources actually changed on the cluster, who approved, what the diff was, whether a rollback was needed. → audit log in Postgres.

Langfuse does **not** know about the second half. The two halves are joined by `trace_id`:

```
Langfuse trace ──trace_id──▶ audit_log (Postgres)
what the LLM intended          what actually changed on the cluster
```

| File | Responsibility |
|---|---|
| `langfuse_client.py` | Initialize the client + CallbackHandler for LangGraph |
| `tracing.py` | Create traces/spans, attach `trace_id` to messages returned to the FE |
| `prompts.py` | Read versioned prompts from Langfuse prompt management |
| `audit.py` | Append-only audit log: actor, action, resource, diff, result, `trace_id` |
| `impact.py` | Join trace ↔ audit: which resources/namespaces the LLM touched, blast radius |
| `evaluation.py` | Dataset + scoring: NL→command accuracy, RCA quality (LLM-as-judge) |
| `metrics.py` | AI operations metrics: approval rate, reject rate, dry-run fail rate, tokens/cost per user |

## Metrics worth tracking (for the thesis evaluation chapter)

**Quality**
- Share of generated plans that pass dry-run (valid manifests)
- Operator approve / reject / manual-edit rate
- NL → intent + target resource accuracy (scored on a fixed dataset)
- RCA: share of rank-1 hypotheses matching the real cause

**Cost & performance**
- Tokens / cost per request, per RCA session
- Latency per graph node (find bottlenecks)
- Average number of tool-call rounds to complete a task

**Safety**
- Number of guardrail blocks (out-of-scope namespace, danger op)
- Number of actions executed in `auto` vs `require_approval` mode
- Number of rollbacks needed after apply
