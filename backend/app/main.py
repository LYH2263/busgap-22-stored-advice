from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.api.router import api_router
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.services.seed import seed_if_empty


def ensure_schema() -> None:
    """create_all 只建新表；对已存在的 bunch_reports 幂等补齐快照列。"""
    inspector = inspect(engine)
    if "bunch_reports" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("bunch_reports")}
    additions = {
        "planned_headway_snapshot": "FLOAT DEFAULT 8.0",
        "bunch_threshold_snapshot": "FLOAT DEFAULT 3.0",
        "large_threshold_snapshot": "FLOAT DEFAULT 15.0",
    }
    with engine.begin() as conn:
        for name, ddl in additions.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE bunch_reports ADD COLUMN {name} {ddl}"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    if settings.seed_on_empty:
        db = SessionLocal()
        try:
            seed_if_empty(db)
        finally:
            db.close()
    yield


app = FastAPI(title="BusGap", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api")
