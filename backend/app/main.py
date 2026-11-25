"""EVAP — Embedded Validation Automation Platform (API)."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import func, select, text

from .config import get_settings
from .db import SessionLocal
from .models import User
from .routers import auth, design, runs
from .security import hash_password

log = logging.getLogger("evap")


def bootstrap_admin() -> None:
    """Create the first admin from environment variables if no user exists yet."""
    s = get_settings()
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(User)):
            return
        if not (s.bootstrap_admin_user and s.bootstrap_admin_password):
            log.warning("No users exist and EVAP_BOOTSTRAP_ADMIN_USER/PASSWORD are not set")
            return
        if len(s.bootstrap_admin_password) < 10:
            raise RuntimeError("EVAP_BOOTSTRAP_ADMIN_PASSWORD must be at least 10 characters")
        db.add(User(username=s.bootstrap_admin_user, role="admin",
                    password_hash=hash_password(s.bootstrap_admin_password)))
        db.commit()
        log.warning("Bootstrap admin '%s' created", s.bootstrap_admin_user)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings()
    bootstrap_admin()
    yield


app = FastAPI(title="EVAP — Embedded Validation Automation Platform", version="1.0.0",
              description="Requirements-driven continuous SIL validation for embedded software.",
              docs_url="/api/docs", openapi_url="/api/openapi.json", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(design.router)
app.include_router(runs.router)


@app.get("/api/health", tags=["meta"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok"}
