# K8s Hub

Nền tảng hỗ trợ vận hành Kubernetes bằng AI: ra lệnh bằng ngôn ngữ tự nhiên, phân tích nguyên nhân gốc (RCA), và chạy runbook thông qua cơ chế skill.

## Use case

| Use case | Backend | Frontend |
|---|---|---|
| **K8s command through NL** | [nl_command/](backend/app/modules/nl_command/) | [chat/](frontend/src/app/(app)/chat/) |
| **RCA** | [rca/](backend/app/modules/rca/) | [rca/](frontend/src/app/(app)/rca/) |
| **Skills** | [skills/](backend/app/modules/skills/) | [skills/](frontend/src/app/(app)/skills/) |
| **Observability (của LLM)** | [observability/](backend/app/modules/observability/) | [observability/](frontend/src/app/(app)/observability/) |

### Ba lớp observability

| Lớp | Giám sát gì | Công cụ | Vị trí |
|---|---|---|---|
| **A** *(use case)* | LLM/agent: prompt, token, cost, tool call, **tác động lên cluster** | Langfuse + audit log | [modules/observability/](backend/app/modules/observability/) |
| **B** | Cụm K8s **đích** — nguồn evidence cho RCA | Prometheus, Loki *(chỉ đọc)* | [integrations/](backend/app/integrations/), [rca/collectors/](backend/app/modules/rca/collectors/) |
| **C** | Chính app K8s-Hub có sống/nhanh không | Prometheus scrape `/metrics`, logs → Loki | [core/telemetry.py](backend/app/core/telemetry.py) |

B và C dùng chung công cụ nhưng ngược chiều: B **đọc** cụm của người khác, C **ghi** số liệu của mình. Langfuse chỉ biết LLM *định* làm gì — phần *thực sự đã đổi gì* nằm ở audit log, nối với nhau bằng `trace_id`.

## Stack

**Backend** — FastAPI · LangGraph · Anthropic Claude · MCP · PostgreSQL + pgvector · Redis · kubernetes-asyncio · Langfuse

**Frontend** — Next.js 15 · TypeScript · Tailwind v4 · shadcn/ui · assistant-ui · TanStack Query · Zustand

## Chạy local

```bash
# 1. Hạ tầng
docker compose -f deploy/local/docker-compose.yml up -d

# 2. Backend
cd backend
uv venv --python 3.12 && source .venv/Scripts/activate
uv pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload

# 3. Frontend
cd frontend
npm install
cp .env.local.example .env.local
npm run dev
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend docs | http://localhost:8000/docs |
| Langfuse | http://localhost:3001 |

## Nguyên tắc an toàn

Mọi hành động thay đổi cluster đi qua pipeline:

```
NL → intent → plan → dry-run/diff → approval gate → execute → verify → audit
```

Chế độ thực thi cấu hình qua `K8S_EXECUTION_MODE`: `read_only` | `require_approval` | `auto`.
