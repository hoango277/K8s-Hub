# K8s Hub - Frontend

Next.js 15 (App Router) + TypeScript + Tailwind v4 + shadcn/ui + assistant-ui.

## Chay local

```bash
npm install
cp .env.local.example .env.local
npm run dev
```

Backend phai chay o `http://localhost:8000` (xem `next.config.ts` -> rewrites).

## Cau truc

```
src/
├── app/
│   ├── (app)/            # khu vuc chinh
│   │   ├── chat/         # USE CASE: NL -> K8s command
│   │   ├── rca/          # USE CASE: root cause analysis
│   │   ├── skills/       # USE CASE: skill catalog + runbook
│   │   ├── observability/# USE CASE: trace, token/cost, cluster metrics
│   │   └── approvals/    # hang doi phe duyet
│   ├── layout.tsx
│   └── globals.css       # Tailwind v4 + shadcn design tokens
├── components/
│   ├── ui/               # shadcn/ui (chay `npx shadcn@latest add ...`)
│   ├── chat/ rca/ skills/ observability/ layout/
├── hooks/                # data fetching + SSE stream
├── lib/                  # api client, sse parser, utils
├── types/                # DTO, khop voi app/schemas cua backend
└── providers/            # React Query provider
```
