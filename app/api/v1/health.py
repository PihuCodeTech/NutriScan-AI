from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.deps import DB, SettingsDep
from app.core.config import APP_VERSION
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.meta import HealthOut

router = APIRouter(tags=["system"])
logger = logging.getLogger(__name__)

DB_CHECK_TIMEOUT_S = 5.0


@router.get(
    "/health",
    response_model=Envelope[HealthOut],
    summary="Service health",
    description="Liveness plus the status of the database, the classifier (`loading|loaded|disabled|error`) and "
    "Gemini (`configured|mock|missing`). No auth.",
)
async def health(request: Request, db: DB, settings: SettingsDep) -> dict:
    try:
        # Bounded, so a down or paused database reports "error" quickly instead of hanging the check.
        await asyncio.wait_for(db.execute(text("SELECT 1")), timeout=DB_CHECK_TIMEOUT_S)
        db_status = "ok"
    except Exception as exc:
        logger.warning("db health check failed", extra={"error": type(exc).__name__})
        db_status = "error"
    data = {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "classifier": request.app.state.classifier.status,
        "gemini": settings.gemini_status,
        "version": APP_VERSION,
    }
    return ok(data)
