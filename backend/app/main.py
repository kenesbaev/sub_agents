from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.config import get_settings
from app.connected_apps.router import router as connected_apps_router
from app.core_domain.router import router as core_domain_router
from app.core_domain.service import backfill_default_workspaces
from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.integrations import router as integrations_router
from app import models  # noqa: F401

settings = get_settings()

app = FastAPI(title=settings.app_name)

allowed_origins = {
    str(settings.frontend_url).rstrip("/"),
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        backfill_default_workspaces(db)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router)
app.include_router(integrations_router)
app.include_router(connected_apps_router)
app.include_router(core_domain_router)
