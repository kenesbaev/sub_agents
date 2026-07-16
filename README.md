# Rebly AI

Full-stack Rebly AI prototype with a Teamly-style landing page, real auth, a FastAPI backend, PostgreSQL, and the original 3D Agent Office embedded behind the dashboard `HIRE` button.

## Stack

- Frontend: Next.js App Router in `frontend/`
- Backend: FastAPI in `backend/`
- Database: PostgreSQL via Docker Compose
- Legacy office: preserved in `frontend/public/office/`

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

## Local Codex Agent

The local agent is a developer-only CLI. It is not connected to the frontend or
any public backend endpoint. It uses the local Codex ChatGPT sign-in, works from
the repository root, and uses the `workspace-write` sandbox.

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
