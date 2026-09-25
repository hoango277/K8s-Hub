# Module: NL -> K8s Command

Pipeline: `NL -> intent -> plan -> dry-run/diff -> approval gate -> execute -> verify`

| File | Responsibility |
|---|---|
| `agent.py` | LangGraph graph, nodes + edges, checkpointer |
| `intent.py` | Intent classification (read / mutate / dangerous) |
| `planner.py` | Generate the plan: manifest or kubectl args |
| `guardrails.py` | Namespace scope, RBAC, blocklist, policy check |
| `dry_run.py` | Server-side dry-run + diff generation |
| `executor.py` | Actually apply, write the audit log |
| `verifier.py` | Post-apply checks (rollout status, pod ready) |
| `state.py` | TypedDict state of the graph |
| `prompts/` | System prompt (may point to Langfuse prompt management) |
