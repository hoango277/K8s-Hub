# Module: NL -> K8s Command

Pipeline: `NL -> intent -> plan -> dry-run/diff -> approval gate -> execute -> verify`

| File | Trach nhiem |
|---|---|
| `agent.py` | LangGraph graph, node + edge, checkpointer |
| `intent.py` | Phan loai y dinh (read / mutate / dangerous) |
| `planner.py` | Sinh ke hoach: manifest hoac kubectl args |
| `guardrails.py` | Namespace scope, RBAC, blocklist, policy check |
| `dry_run.py` | Server-side dry-run + sinh diff |
| `executor.py` | Apply that su, ghi audit log |
| `verifier.py` | Kiem tra sau khi apply (rollout status, pod ready) |
| `state.py` | TypedDict state cua graph |
| `prompts/` | System prompt (co the tro toi Langfuse prompt management) |
