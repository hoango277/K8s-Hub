# Module: NL -> K8s Command

Pipeline: `question -> agent (read tools) -> write tool PROPOSES -> plan -> guardrails
-> server-side dry-run + diff -> approval (engineer) -> execute -> verify -> note in chat`

| File | Responsibility |
|---|---|
| `agent.py` | LangGraph graph; tool budget (`MAX_TOOL_ROUNDS`) then a forced answer; history incl. system notes |
| `tools.py` | Core tools (`system_info`, `current_time`) + the per-turn tool list |
| `intent.py` | Custom CLI calls: split arguments (no shell), read vs change by read-only prefixes, refused flags |
| `guardrails.py` | read_only mode, protected namespaces (kube-system, sandbox…), danger of a kind |
| `planner.py` | Exact, storable plans: scale, restart, set_image, delete_pod, apply (SSA), command |
| `dry_run.py` | `dryRun=All` on the API server + diff; `--dry-run=server` for kubectl, `--dry-run` for helm |
| `executor.py` | Run an APPROVED plan exactly as stored |
| `verifier.py` | After running: rollout settled? object gone? object present? |
| `state.py` | TypedDict state of the graph |
| `prompts/` | System prompt |

The approval itself (store, decide, expire, report back) is
`app/services/approval_service.py`; API `app/api/v1/approvals.py`.

Unlike kubectl-ai, the turn does not pause for the human: the proposal is
stored, the turn ends, and the decision (by any engineer/admin, later) is
written back into the conversation as a system note the model reads next turn.
