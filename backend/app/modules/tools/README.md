# Module: Tools

Code the assistant can call. Skills (`app/modules/skills/`) are instructions on
top of these.

| File | Responsibility |
|---|---|
| `schema.py` | `ToolSpec`: a LangChain tool + title, category, danger level, source, availability |
| `registry.py` | The one catalog: built-in tools + custom tools; decides what reaches the chat |
| `guard.py` | Checks every tool applies: namespace allowed-list, name formats |
| `custom.py` | Custom CLI tools (kubectl-ai style) + the kubectl/helm templates |
| `mcp.py` | Tools of external MCP servers, behind a per-tool policy (enabled, requires approval) |
| `mcp_client.py` | List/call the tools of an MCP server (Streamable HTTP, `mcp` 2.x) |
| `builtin/kubernetes.py` | `list_pods`, `describe_pod`, `get_pod_logs`, `list_events`, `list_deployments` |
| `builtin/resources.py` | `get_resources`, `describe_resource` — any kind (services, ingresses, nodes, PVCs, CRDs…), never Secrets |
| `builtin/metrics.py` | `pod_metrics` — fixed PromQL templates, never PromQL from the model |
| `builtin/logs.py` | `search_logs` — LogQL built from validated fields |
| `builtin/traces.py` | `list_traced_services`, `search_traces`, `get_trace` (Tempo) |
| `builtin/actions.py` | WRITE tools that only **propose**: `scale_workload`, `restart_workload`, `set_image`, `delete_pod`, `apply_manifest` |

Rules:
- READ tools run when called. WRITE/DESTRUCTIVE tools never change anything:
  they build a plan, the API server dry-runs it, and it waits for an engineer's
  approval (`app/services/approval_service.py`). In `read_only` mode they are
  not offered.
- Custom tools: the engineer fixes the program and its read-only subcommands;
  the model writes only the arguments. No shell (argv list). Reads run in the
  sandbox; anything else becomes an approval. Secrets, `-w/--watch`, `logs -f`,
  `exec -it`, `port-forward` are refused.
- The model never writes PromQL, LogQL or TraceQL, and never gets raw results:
  queries come from templates/checked fields, results are summarised.
- External MCP servers (back on 01/10/2026): only engineers/admins connect them and
  set each tool's policy. New tools start disabled and requiring approval, whatever
  the server claims. A tool requiring approval stores the exact call as a pending
  approval; the server is called only after an engineer approves. The policy is
  read at call time.

Persistence and runs: `app/services/tool_service.py`. API: `app/api/v1/tools.py`.
