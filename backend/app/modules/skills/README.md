# Module: Skills

Moi skill = 1 don vi nang luc dong goi (tuong duong 1 MCP server / tool group),
duoc agent goi den. Runbook la 1 loai skill co nhieu buoc.

| File | Trach nhiem |
|---|---|
| `schema.py` | SkillManifest: name, description, input schema, permission, danger level |
| `registry.py` | Dang ky / tra cuu skill, expose sang LLM duoi dang tool definition |
| `loader.py` | Nap skill tu builtin + MCP server ben ngoai |
| `executor.py` | Chay skill, stream progress, ghi audit |
| `mcp_client.py` | Ket noi toi MCP server, list tools, call tool |
| `runbook.py` | Skill nhieu buoc: parse, chay tuan tu, retry, rollback |
| `builtin/` | Cac skill dung san |
