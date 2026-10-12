from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import DB, LLM, CurrentUser
from app.api.v1.docs import AI, AUTH, errors
from app.core.rate_limit import ai_limit, limiter
from app.core.responses import ok
from app.schemas.common import Envelope, Page
from app.schemas.intake import (
    DailyIntakeOut,
    DescribeIn,
    DescribeOut,
    IntakeEntryOut,
    IntakeSummaryOut,
    ManualIntakeIn,
)
from app.services import intake_service

router = APIRouter(prefix="/intake", tags=["intake"])


@router.post(
    "/describe",
    response_model=Envelope[DescribeOut],
    summary="Estimate a meal from text",
    description="Gemini estimates items from a description like '2 roti, dal and a glass of lassi'. Returns "
    "items, server-computed totals and health. With `log=true` it is also saved (source `description`).",
    responses=errors(*AUTH, "NOT_FOOD", "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def describe(request: Request, body: DescribeIn, user: CurrentUser, db: DB, llm: LLM) -> dict:
    data = await intake_service.describe(db, user, text=body.text, meal_type=body.meal_type, log=body.log, llm=llm)
    return ok(data, "DESCRIPTION_ANALYSED", "Meal estimated" + (" and logged" if body.log else ""))


@router.post(
    "",
    status_code=201,
    response_model=Envelope[IntakeEntryOut],
    summary="Log a meal manually",
    description="For when the frontend already has the numbers. Totals are computed server-side.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def create_manual(body: ManualIntakeIn, user: CurrentUser, db: DB) -> dict:
    entry = await intake_service.create_manual(db, user, body)
    return ok(intake_service.to_out(entry), "INTAKE_LOGGED", "Meal logged")


@router.get(
    "",
    response_model=Envelope[Page[IntakeEntryOut]],
    summary="List intake entries",
    description="Entries from the last `days` local days (1–90, default 30), newest first, paginated. "
    "Used for history screens; use `/intake/daily` for one day with totals and targets.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def list_entries(
    user: CurrentUser,
    db: DB,
    days: Annotated[int, Query(ge=1, le=90)] = 30,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    entries, total = await intake_service.list_entries(db, user, days=days, page=page, page_size=page_size)
    items = [intake_service.to_out(e) for e in entries]
    return ok({"items": items, "page": page, "page_size": page_size, "total": total})


@router.get(
    "/daily",
    response_model=Envelope[DailyIntakeOut],
    summary="Daily intake",
    description="Entries for a local date (default today), totals vs targets, remaining, percent of target, "
    "`health_status` (`on_track|over|under|no_data`) and status flags for chips.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def daily(
    user: CurrentUser, db: DB, date: Annotated[date | None, Query(description="YYYY-MM-DD; default today")] = None
) -> dict:
    return ok(await intake_service.daily(db, user, date))


@router.get(
    "/summary",
    response_model=Envelope[IntakeSummaryOut],
    summary="Multi-day summary",
    description="Last `days` days (1–31, zero-filled), averages over logged days, current logging streak and "
    "most frequent foods.",
    responses=errors(*AUTH, "VALIDATION_ERROR"),
)
async def summary(user: CurrentUser, db: DB, days: Annotated[int, Query(ge=1, le=31)] = 7) -> dict:
    return ok(await intake_service.summary(db, user, days))


@router.delete(
    "/{entry_id}",
    response_model=Envelope[None],
    summary="Delete an intake entry",
    description="Removes the entry from your log. If it came from a scan, that scan can be logged again.",
    responses=errors(*AUTH, "NOT_FOUND"),
)
async def delete_entry(entry_id: str, user: CurrentUser, db: DB) -> dict:
    await intake_service.delete_entry(db, user, entry_id)
    return ok(None, "DELETED", "Entry deleted")
