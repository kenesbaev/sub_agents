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

## Google OAuth

Set these in `backend/.env`:

```txt
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://localhost:8000/api/auth/google/callback
```

The Google Cloud OAuth client must allow this redirect URI.
