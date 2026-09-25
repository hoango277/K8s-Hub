# Module: Skills

Each skill = one packaged unit of capability (equivalent to one MCP server /
tool group) that the agent calls. A runbook is a kind of skill with multiple steps.

| File | Responsibility |
|---|---|
| `schema.py` | SkillManifest: name, description, input schema, permission, danger level |
| `registry.py` | Register / look up skills, expose them to the LLM as tool definitions |
| `loader.py` | Load skills from builtin + external MCP servers |
| `executor.py` | Run skills, stream progress, write audit |
| `mcp_client.py` | Connect to MCP servers, list tools, call tool |
| `runbook.py` | Multi-step skills: parse, run sequentially, retry, rollback |
| `builtin/` | Ready-made skills |
