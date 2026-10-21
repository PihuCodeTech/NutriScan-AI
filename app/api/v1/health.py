from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.api.deps import DB, SettingsDep
from app.api.v1.docs import errors
from app.core.config import APP_VERSION, Settings
from app.core.responses import fail, ok
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
    return ok(await _status(request, db, settings))


@router.get(
    "/health/ready",
    response_model=Envelope[HealthOut],
    summary="Readiness (for uptime monitors)",
    description="Same body as `/health`, but answers **503 NOT_READY** when the database is unreachable, so an "
    "external uptime monitor or load balancer can alert on (or route around) it. `/health` stays 200 for the "
    "container's liveness check: a database outage shouldn't restart the API. No auth.",
    responses=errors("NOT_READY"),
)
async def ready(request: Request, db: DB, settings: SettingsDep) -> object:
    data = await _status(request, db, settings)
    if data["db"] != "ok":
        return fail("NOT_READY", "The database is unreachable.", 503, details=data)
    return ok(data)


async def _status(request: Request, db: DB, settings: Settings) -> dict:
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
    return data
