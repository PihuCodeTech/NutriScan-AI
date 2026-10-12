from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import DB, LLM, CurrentUser
from app.api.v1.docs import AI, AUTH, errors
from app.core.rate_limit import ai_limit, limiter
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.insight import DailyInsightOut
from app.services import insight_service

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get(
    "/daily",
    response_model=Envelope[DailyInsightOut],
    summary="Daily insight",
    description="Encouraging headline, 2-sentence summary and 3 tips written by Gemini over the day's "
    "server-computed numbers. Cached per (user, date, totals); `no_data` days get a static nudge without "
    "an AI call.",
    responses=errors(*AUTH, "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def daily_insight(
    request: Request,
    user: CurrentUser,
    db: DB,
    llm: LLM,
    date: Annotated[date | None, Query(description="YYYY-MM-DD; default today")] = None,
) -> dict:
    return ok(await insight_service.daily_insight(db, user, date, llm))
