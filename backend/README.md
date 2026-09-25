# K8s Hub — Backend

FastAPI backend for the AI-assisted Kubernetes operations platform.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows

cp .env.example .env
PYTHONUTF8=1 .venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs · Health: http://localhost:8000/api/v1/health

## Layout

```
app/
├── main.py              # entrypoint, wiring only
├── api/v1/              # HTTP layer, one router file per use case
├── core/                # config, logging, security, permissions
│   └── telemetry.py     # self-monitoring: /metrics + structured logs of THIS app
├── db/                  # engine, session, SQLAlchemy models
├── schemas/             # Pydantic DTOs (including the SSE event schema)
├── modules/             # ── the 4 main use cases ──
│   ├── nl_command/      # NL → K8s command (plan → dry-run → approve → execute)
│   ├── rca/             # Root cause analysis (collect → correlate → hypothesize)
│   ├── skills/          # Skill registry + MCP + runbook engine
│   └── observability/   # LLM monitoring: Langfuse traces + audit + impact + eval
├── integrations/        # Clients for external systems: k8s, prometheus, loki, llm
├── services/            # Orchestration between api ↔ modules ↔ db
└── workers/             # Background jobs (long runbooks, scheduled RCA)
```

Each module has its own `README.md` describing its pipeline and what each file is responsible for.

## Three observability layers — don't mix them up

| Layer | What it watches | Where | Tools |
|---|---|---|---|
| **A** | LLM/agent: prompts, tokens, cost, tool calls, impact | `modules/observability/` | Langfuse + audit log |
| **B** | The **target** K8s cluster (evidence for RCA) | `integrations/prometheus`, `integrations/loki` | Prometheus, Loki (read-only) |
| **C** | Whether the K8s-Hub app itself is alive and fast | `core/telemetry.py` | Prometheus scrapes `/metrics`, logs → Loki |

B and C share tools but point in opposite directions: B **reads** someone else's cluster, C **writes** our own numbers.
