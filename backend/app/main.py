import asyncio
from contextlib import suppress
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.config import get_settings
from app.connected_apps.router import router as connected_apps_router
from app.core_domain.router import router as core_domain_router
from app.core_domain.service import backfill_default_workspaces
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.health import readiness_report
from app.integrations import router as integrations_router
from app.youtube_growth.router import router as youtube_growth_router
from app.youtube_growth.runtime import run_snapshot_worker
from app import models

settings = get_settings()
# Importing the model module registers every ORM table before startup schema
# compatibility checks and development-only metadata creation run.
MODEL_REGISTRY = models

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "X-Requested-With"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hostnames())


@app.middleware("http")
async def production_request_guard(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", request_id):
        request_id = uuid.uuid4().hex
    request.state.request_id = request_id

    if settings.is_production and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("Origin", "").strip().rstrip("/")
        if origin and origin not in settings.allowed_cors_origins():
            return JSONResponse(
                {"detail": "Origin is not allowed", "requestId": request_id},
                status_code=403,
                headers={"X-Request-ID": request_id},
            )

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.on_event("startup")
def on_startup() -> None:
    if settings.auto_create_schema_enabled:
        Base.metadata.create_all(bind=engine)
    if settings.startup_backfill_enabled:
        with SessionLocal() as db:
            backfill_default_workspaces(db)


@app.on_event("startup")
async def start_youtube_snapshot_worker() -> None:
    if not settings.youtube_snapshot_worker_enabled or not settings.youtube_snapshot_worker_run_in_api:
        return
    stop_event = asyncio.Event()
    app.state.youtube_snapshot_worker_stop = stop_event
    app.state.youtube_snapshot_worker_task = asyncio.create_task(
        run_snapshot_worker(stop_event, settings, SessionLocal),
        name="youtube-growth-snapshot-worker",
    )


@app.on_event("shutdown")
async def stop_youtube_snapshot_worker() -> None:
    task = getattr(app.state, "youtube_snapshot_worker_task", None)
    stop_event = getattr(app.state, "youtube_snapshot_worker_stop", None)
    if stop_event is not None:
        stop_event.set()
    if task is None:
        return
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/livez", include_in_schema=False)
def livez() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz", include_in_schema=False)
def readyz() -> JSONResponse:
    ready, payload = readiness_report(engine)
    return JSONResponse(payload, status_code=200 if ready else 503)


app.include_router(auth_router)
app.include_router(integrations_router)
app.include_router(connected_apps_router)
app.include_router(core_domain_router)
app.include_router(youtube_growth_router)
