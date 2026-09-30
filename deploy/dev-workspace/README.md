# Dev workspace on lab1

Code K8s-Hub from a VS Code that runs **inside** the lab1 cluster (code-server),
so the app talks to Postgres, Prometheus, Loki, Tempo and Langfuse by service
name and to the Kubernetes API with the pod's ServiceAccount — no kubeconfig
file, no NodePort juggling.

## 1. Create it (on lab1, as cluster admin)

```bash
kubectl apply -f workspace.yaml
kubectl -n k8s-hub-dev create secret generic workspace-auth \
  --from-literal=password='<strong password>'
kubectl -n k8s-hub-dev rollout status deploy/workspace
```

Open `http://<lab1>:30880` and log in with that password. The first start
installs uv + Python 3.12, Node 22 (fnm), kubectl and helm into the home volume
in the background — follow it with `tail -f ~/bootstrap.log` in the terminal.

## 2. Get the code in

In the workspace terminal:

```bash
git clone <your repo URL> ~/K8s-Hub      # or: kubectl cp from your laptop
cd ~/K8s-Hub/backend && uv venv --python 3.12 && uv pip install -r requirements-dev.txt
cp ../deploy/dev-workspace/env.cluster.example .env   # then fill in the secrets
cd ../frontend && npm ci && cp .env.local.example .env.local
```

## 3. Run

| What | Command (workspace terminal) | Open in your browser |
|---|---|---|
| Backend | `cd backend && .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --reload` | `http://<lab1>:30808/docs` |
| Frontend | `cd frontend && npm run dev -- --hostname 0.0.0.0` | `http://<lab1>:30830` |

Bind to `0.0.0.0`, not localhost — the NodePort reaches the pod from outside.

Check the cluster access: `kubectl auth can-i list pods -A` → yes,
`kubectl auth can-i delete pods -n default` → no.

## What the workspace may do

| Scope | Permission | Why |
|---|---|---|
| Whole cluster | `view` (read, no Secrets) | What K8s-Hub's tools need |
| Namespace `k8s-hub` | `edit` | Deploy the app later with helm |
| Everything else | nothing | A shell in the cluster is powerful; keep it narrow |

The backend you run in the workspace inherits these permissions. The real
deployment (namespace `k8s-hub`) will get its own view-only ServiceAccount.

## Security notes

- code-server is a shell inside the cluster. Keep the password strong and the
  NodePort off the public internet.
- Extensions come from Open VSX, not the Microsoft marketplace (no Pylance —
  use basedpyright/Pyright). Prefer VS Code desktop? Attach to this pod with the
  Kubernetes or Dev Containers extension instead of the browser.
