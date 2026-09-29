# Module: Tools

Code the assistant can call. Skills (`app/modules/skills/`) are instructions on
top of these.

| File | Responsibility |
|---|---|
| `schema.py` | `ToolSpec`: a LangChain tool + title, category, danger level, source, availability |
| `registry.py` | The one catalog: built-in tools + tools of connected MCP servers; decides what reaches the chat |
| `guard.py` | Checks every built-in tool applies: namespace allowed-list, name formats |
| `mcp_client.py` | List/call tools of an external MCP server (Streamable HTTP) |
| `builtin/kubernetes.py` | `list_pods`, `describe_pod`, `get_pod_logs`, `list_events`, `list_deployments` |
| `builtin/metrics.py` | `pod_metrics` — fixed PromQL templates, never PromQL from the model |
| `builtin/logs.py` | `search_logs` — LogQL built from validated fields |
| `builtin/traces.py` | `list_traced_services`, `search_traces`, `get_trace` (Tempo) |

Rules:
- Only enabled, available **read** tools reach the chat agent. Write tools wait
  for the approval flow.
- External (MCP) tools start **disabled and "write"**, whatever the server claims
  (`readOnlyHint` is shown, never trusted), until an engineer reviews them.
- The model never writes PromQL, LogQL or TraceQL, and never gets raw results:
  queries come from templates/checked fields, results are summarised.

Persistence and runs: `app/services/tool_service.py`. API: `app/api/v1/tools.py`.
