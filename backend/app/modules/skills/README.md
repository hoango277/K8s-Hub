# Module: Skills (Agent Skills standard)

A **skill** is a folder that teaches the agent HOW to do a task:

```
<name>/
  SKILL.md        YAML front matter (name, description) + instructions
  scripts/        optional — code the agent can run (in the sandbox, see below)
  references/     optional — documents the agent reads when needed
  assets/         optional — templates, examples
```

Same format as Claude Code and other agents: export a skill as .zip here, use it
there, and the other way round.

A skill is NOT a tool. **Tools** (`app/modules/tools/`) are code the model calls —
read pods, query metrics, search logs, explain a trace, MCP tools. Skills sit on
top: they tell the agent which tools to use, in which order, and how to read the
results.

## Progressive disclosure

| Level | What the model gets | When |
|---|---|---|
| 1 | name + description of every enabled skill, in the system prompt | every turn |
| 2 | the SKILL.md instructions (`load_skill`) | when a request matches |
| 3 | a reference/asset (`read_skill_file`) or a script run (`run_skill_script`) | when the instructions say so |

## Files

| File | Responsibility |
|---|---|
| `parser.py` | Validate a skill folder: front matter, name rules, safe paths, size limits |
| `store.py` | In-memory list of skills (built-in from `backend/skills/` + custom from the DB) |
| `agent_tools.py` | `skills_prompt()` and the three tools the agent uses |
| `scripts.py` | Checks a script run (scripts/ only, .py/.sh, argument limits) and hands it to the sandbox |

Persistence, import/export and run history: `app/services/skill_service.py`.
API: `app/api/v1/skills.py`. Built-in skills: `backend/skills/`.

## Where scripts run — the sandbox

`SANDBOX_BACKEND` (`app/modules/sandbox/`) decides:

- `local` — a subprocess on the backend: no shell, stripped environment, temp
  dir, time limit. Guard rails, not isolation (the original 29/09/2026 choice).
- `kubernetes` — the `runner` container of the sandbox pod
  (`deploy/sandbox/sandbox.yaml`): no ServiceAccount token, no backend secrets,
  read-only root filesystem.

Either way, whoever can edit a skill can run code there, so editing is
engineer+ only.
