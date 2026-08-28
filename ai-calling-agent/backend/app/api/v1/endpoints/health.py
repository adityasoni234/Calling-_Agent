from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app import __version__
from app.api.deps import DbSession
from app.core.config import settings
from app.schemas.common import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and dependency check")
async def health(db: DbSession) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except Exception:  # pragma: no cover - exercised only when Postgres is down
        database = "unavailable"

    return HealthResponse(
        status="ok" if database == "ok" else "degraded",
        app=settings.app_name,
        environment=settings.app_env,
        version=__version__,
        database=database,
    )
