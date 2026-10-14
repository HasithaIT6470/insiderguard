import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from . import config
from .api import router
from .database import SessionLocal, init_db
from .models import User
from .pipeline import seed_rule_config
from .security import hash_password

log = logging.getLogger("insiderguard")

@asynccontextmanager
async def lifespan(_app):
    startup()
    yield


app = FastAPI(
    lifespan=lifespan,
    title="InsiderGuard API",
    version="1.0.0",
    description="AI-assisted insider threat detection and data-exfiltration prevention (UEBA prototype). "
    "Synthetic data only.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(router)


def startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        seed_rule_config(db)
        if config.ENV != "production" and db.scalar(select(User).limit(1)) is None:
            db.add(User(username=config.DEFAULT_ADMIN_USER, role="admin",
                        password_hash=hash_password(config.DEFAULT_ADMIN_PASSWORD, config.DEFAULT_ADMIN_USER)))
            db.add(User(username=config.DEFAULT_ANALYST_USER, role="analyst",
                        password_hash=hash_password(config.DEFAULT_ANALYST_PASSWORD, config.DEFAULT_ANALYST_USER)))
            db.commit()
            log.warning("Seeded development accounts '%s' and '%s'. Change these passwords or set "
                        "INSIDERGUARD_ADMIN_PASSWORD / INSIDERGUARD_ANALYST_PASSWORD.",
                        config.DEFAULT_ADMIN_USER, config.DEFAULT_ANALYST_USER)
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok"}
