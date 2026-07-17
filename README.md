# Teamora AI / Rebly AI

Full-stack AI team workspace with a Next.js frontend, FastAPI API, PostgreSQL,
authenticated AI Agent service, Connected Apps, YouTube Growth analysis, and the
3D Agent Office.

## Stack

- Frontend: Next.js App Router in `frontend/`
- Backend: FastAPI in `backend/`
- Database: PostgreSQL via Docker Compose
- AI runtime: authenticated Python Agent API with OpenRouter
- Workers: YouTube snapshots and at-most-once scheduled social delivery
- 3D Office: served from `frontend/public/office/`

## Production

Use [deploy/PRODUCTION.md](deploy/PRODUCTION.md) as the deployment and recovery
runbook. Production uses `compose.production.yml`; it does not use the local
development Compose file. Schema changes are owned only by Alembic, and
PostgreSQL/backend/agent/frontend ports stay private behind Nginx; Redis is not
deployed because no production runtime component currently uses it.

Production intentionally disables local password registration, arbitrary link
fetching/video downloads, the Codex CLI fallback, and YouTube URL upload. Those
paths require stronger abuse controls or durable idempotent jobs before they can
be enabled safely. Google login, AI chat/team runs, Connected Apps status,
Google read actions, YouTube Growth analysis, approved Telegram/Instagram publishing,
and the dedicated scheduled-post worker remain available when configured.
The standalone Telegram bot bridge is excluded from production until it has an
explicit application-user linking flow.
Google write actions remain disabled until they have durable idempotency and
unknown-outcome reconciliation.

## Local Run

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Run the backend:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Run the frontend:

```bash
cd frontend
npm install
npm run dev
```

Open:

```txt
http://localhost:3000
```

This workspace was verified with Node 22 for Next.js build/start.

## Local Codex Agent CLI

The separate local Codex helper is developer-only and is not used by the
production Agent service. Production uses the configured provider API and keeps
the CLI fallback disabled.

From the project root, install its isolated dependency into the existing backend
virtual environment:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r tools\requirements-local-codex.txt
```

Sign in once with the ChatGPT account that has your Codex subscription:

```powershell
codex login
codex login status
```

Then run a task. If the virtual environment is activated, `python` is enough:

```powershell
python tools\local_codex_agent.py "Проверь backend и найди ошибки"
```

Or run it directly through the project virtual environment:

```powershell
backend\.venv\Scripts\python.exe tools\local_codex_agent.py "Проверь backend и найди ошибки"
```

The command checks `codex login status` before each task. If there is no active
ChatGPT sign-in, it tells you to run `codex login`. It does not require an API
key, does not use OpenRouter, and never reads, copies, or prints
`~/.codex/auth.json`.

## Google OAuth

Set these in `backend/.env`:

```txt
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

The Google Cloud OAuth client must allow this redirect URI.
