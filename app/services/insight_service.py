"""Daily insight: Gemini text over the day's numbers, cached per (user, date, totals_hash)."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DISCLAIMER
from app.db.models import InsightCache, User
from app.services import intake_service
from app.services.llm.gemini_client import LLMClient
from app.services.user_service import user_context
from app.utils.timeutil import get_tz, now_local

logger = logging.getLogger(__name__)

TIPS_COUNT = 3


def totals_hash(totals: dict[str, Any], health_status: str) -> str:
    """sha256 of the day's totals JSON (plus status, which can change with the clock)."""
    blob = json.dumps({"totals": totals, "health_status": health_status}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _normalise_tips(tips: list[str]) -> list[str]:
    """Gemini's tips, trimmed and capped at 3. Never padded with canned text."""
    return [t.strip() for t in tips if t and t.strip()][:TIPS_COUNT]


async def daily_insight(db: AsyncSession, user: User, day: date | None, llm: LLMClient) -> dict[str, Any]:
    data = await intake_service.daily(db, user, day)
    day = data["date"]
    status = data["health_status"]
    base = {"date": day, "health_status": status, "disclaimer": DISCLAIMER}

    digest = totals_hash(data["totals"], status)
    cached = await db.scalar(
        select(InsightCache).where(
            InsightCache.user_id == user.id, InsightCache.date == day, InsightCache.totals_hash == digest
        )
    )
    if cached is not None:
        return {**base, **cached.payload}

    local_now = now_local(get_tz(user.profile.timezone if user.profile else None))
    day_summary = {
        "date": day.isoformat(),
        "local_time": local_now.strftime("%H:%M") if day == local_now.date() else "day is over",
        "health_status": status,
        "totals": data["totals"],
        "targets": data["targets"],
        "percent_of_target": data["percent_of_target"],
        "entries": [{"name": e["name"], "meal_type": e["meal_type"]} for e in data["entries"]],
    }
    result = await llm.daily_insight(day_summary=day_summary, user_ctx=user_context(user))
    payload = {
        "headline": result.headline.strip()[:120] or "Keep going!",
        "summary": result.summary.strip(),
        "tips": _normalise_tips(result.tips),
    }
    db.add(InsightCache(user_id=user.id, date=day, totals_hash=digest, payload=payload))
    try:
        await db.commit()
    except IntegrityError:  # a concurrent request cached the same key first
        await db.rollback()
    return {**base, **payload}
