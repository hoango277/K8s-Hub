# K8s Hub — Backend

FastAPI backend cho nền tảng vận hành Kubernetes có AI hỗ trợ.

## Chạy local

```bash
uv venv --python 3.12
source .venv/Scripts/activate     # Windows Git Bash
uv pip install -e ".[dev]"

cp .env.example .env
uvicorn app.main:app --reload
```

Docs: http://localhost:8000/docs · Health: http://localhost:8000/api/v1/health

## Cấu trúc

```
app/
├── main.py              # entrypoint, chỉ wiring
├── api/v1/              # HTTP layer, mỗi use case 1 file router
├── core/                # config, logging, security, permissions
│   └── telemetry.py     # self-monitoring: /metrics + structured logs của CHÍNH app này
├── db/                  # engine, session, SQLAlchemy models
├── schemas/             # Pydantic DTO (bao gồm SSE event schema)
├── modules/             # ── 4 use case chính ──
│   ├── nl_command/      # NL → K8s command (plan → dry-run → approve → execute)
│   ├── rca/             # Root cause analysis (collect → correlate → hypothesize)
│   ├── skills/          # Skill registry + MCP + runbook engine
│   └── observability/   # Giám sát LLM: Langfuse trace + audit + impact + eval
├── integrations/        # Client tới hệ thống ngoài: k8s, prometheus, loki, llm
├── services/            # Orchestration giữa api ↔ modules ↔ db
└── workers/             # Background job (runbook dài, RCA theo lịch)
```

Mỗi module có `README.md` riêng mô tả pipeline và trách nhiệm từng file.

## Ba lớp observability — đừng nhầm

| Lớp | Giám sát gì | Ở đâu | Công cụ |
|---|---|---|---|
| **A** | LLM/agent: prompt, token, cost, tool call, tác động | `modules/observability/` | Langfuse + audit log |
| **B** | Cụm K8s **đích** (evidence cho RCA) | `integrations/prometheus`, `integrations/loki` | Prometheus, Loki (chỉ đọc) |
| **C** | Chính app K8s-Hub có sống/nhanh không | `core/telemetry.py` | Prometheus scrape `/metrics`, logs → Loki |

B và C dùng chung công cụ nhưng ngược chiều: B **đọc** cụm của người khác, C **ghi** số liệu của mình.
