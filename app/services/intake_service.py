"""Intake logging, daily view and multi-day summary."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, not_found
from app.db.models import IntakeEntry, Scan, User
from app.schemas.intake import ManualIntakeIn
from app.services.health_engine import (
    compute_targets,
    daily_status,
    daily_status_flags,
    percent_of_target,
    remaining,
    score_meal,
)
from app.services.llm.gemini_client import LLMClient
from app.services.nutrition import NUTRIENT_KEYS, aggregate, canonicalize, coerce, round_nutrients
from app.services.user_service import user_context
from app.utils.timeutil import default_meal_type, ensure_utc, get_tz, local_date_of, now_local, utcnow

TOP_FOODS_LIMIT = 5


def _tz(user: User) -> ZoneInfo:
    return get_tz(user.profile.timezone if user.profile else None)


def today_for(user: User) -> date:
    return now_local(_tz(user)).date()


def build_entry(
    user: User,
    *,
    source: str,
    name: str,
    meal_type: str,
    eaten_at: datetime | None,
    items: list[dict[str, Any]],
    scan_id: str | None = None,
) -> IntakeEntry:
    """Construct (not persist) an intake entry; totals are always computed server-side."""
    eaten = ensure_utc(eaten_at) if eaten_at else utcnow()
    snapshot = [
        {
            "id": i.get("id") or str(uuid.uuid4()),
            "name": i["name"],
            "canonical_name": i.get("canonical_name") or canonicalize(i["name"]),
            "quantity_g": i["quantity_g"],
            "serving_description": i.get("serving_description"),
            "confidence": i.get("confidence", "high"),
            "source": i.get("source", "ai"),
            "nutrients": round_nutrients(coerce(i["nutrients"])),
        }
        for i in items
    ]
    return IntakeEntry(
        user_id=user.id,
        source=source,
        scan_id=scan_id,
        name=name.strip()[:120] or "Meal",
        meal_type=meal_type,
        eaten_at=eaten,
        local_date=local_date_of(eaten, _tz(user)),
        items=snapshot,
        totals=aggregate(i["nutrients"] for i in snapshot),
    )


def to_out(entry: IntakeEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "source": entry.source,
        "scan_id": entry.scan_id,
        "name": entry.name,
        "meal_type": entry.meal_type,
        "eaten_at": entry.eaten_at,
        "items": entry.items,
        "totals": entry.totals,
    }


async def estimate_description(
    user: User, text: str, llm: LLMClient
) -> tuple[str | None, list[dict[str, Any]], dict[str, float], list[str]]:
    """Gemini text estimate → (meal_name, FoodItem dicts, totals, tips). NOT_FOOD if it isn't food."""
    from app.services.scan_service import item_from_llm  # local import avoids a cycle

    est = await llm.estimate_from_text(text, user_ctx=user_context(user))
    if not est.is_food or not est.items:
        raise AppError(
            "NOT_FOOD",
            "That doesn't look like a food description.",
            422,
            {"reason": est.rejection_reason},
        )
    items = []
    for it in est.items:
        d = item_from_llm(it)
        d.pop("nutrients_per_100g", None)
        d["id"] = str(uuid.uuid4())
        items.append(d)
    totals = aggregate(i["nutrients"] for i in items)
    return est.meal_name, items, totals, [t.strip() for t in est.tips if t.strip()][:3]


async def describe(
    db: AsyncSession, user: User, *, text: str, meal_type: str | None, log: bool, llm: LLMClient
) -> dict[str, Any]:
    meal_type = meal_type or default_meal_type(now_local(_tz(user)))
    meal_name, items, totals, tips = await estimate_description(user, text, llm)
    health = score_meal(totals, compute_targets(user.profile).nutrients, meal_type, tips=tips)
    out: dict[str, Any] = {
        "meal_name": meal_name,
        "items": items,
        "totals": totals,
        "health": health,
        "intake_entry": None,
    }
    if log:
        entry = build_entry(
            user, source="description", name=meal_name or text[:60], meal_type=meal_type, eaten_at=None, items=items
        )
        db.add(entry)
        await db.commit()
        out["intake_entry"] = to_out(entry)
    return out


async def create_manual(db: AsyncSession, user: User, data: ManualIntakeIn) -> IntakeEntry:
    items = [
        {
            "name": i.name,
            "canonical_name": canonicalize(i.name),
            "quantity_g": round(i.quantity_g, 1) if i.quantity_g else 0.0,
            "serving_description": i.serving_description or (f"{i.quantity_g:g} g" if i.quantity_g else "1 serving"),
            "confidence": "high",
            "source": "user_added",
            "nutrients": i.nutrients.model_dump(),
        }
        for i in data.items
    ]
    entry = build_entry(
        user, source="manual", name=data.name, meal_type=data.meal_type, eaten_at=data.eaten_at, items=items
    )
    db.add(entry)
    await db.commit()
    return entry


async def create_from_chat(
    db: AsyncSession, user: User, *, description: str, meal_type: str, eaten_at: datetime | None, llm: LLMClient
) -> IntakeEntry:
    meal_name, items, _totals, _tips = await estimate_description(user, description, llm)
    entry = build_entry(
        user, source="chat", name=meal_name or description[:60], meal_type=meal_type, eaten_at=eaten_at, items=items
    )
    db.add(entry)
    await db.commit()
    return entry


async def delete_entry(db: AsyncSession, user: User, entry_id: str) -> None:
    entry = await db.scalar(select(IntakeEntry).where(IntakeEntry.id == entry_id, IntakeEntry.user_id == user.id))
    if entry is None:
        raise not_found("Intake entry")
    await db.execute(update(Scan).where(Scan.logged_intake_id == entry.id).values(logged_intake_id=None))
    await db.delete(entry)
    await db.commit()


async def list_entries(
    db: AsyncSession, user: User, *, days: int, page: int, page_size: int
) -> tuple[list[IntakeEntry], int]:
    """Entries from the last `days` local days (today included), newest first."""
    start = today_for(user) - timedelta(days=days - 1)
    conditions = [IntakeEntry.user_id == user.id, IntakeEntry.local_date >= start]
    total = await db.scalar(select(func.count()).select_from(IntakeEntry).where(*conditions)) or 0
    rows = await db.scalars(
        select(IntakeEntry)
        .where(*conditions)
        .order_by(IntakeEntry.eaten_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(rows), total


async def entries_for_day(db: AsyncSession, user: User, day: date) -> list[IntakeEntry]:
    rows = await db.scalars(
        select(IntakeEntry)
        .where(IntakeEntry.user_id == user.id, IntakeEntry.local_date == day)
        .order_by(IntakeEntry.eaten_at)
    )
    return list(rows)


async def daily(db: AsyncSession, user: User, day: date | None = None) -> dict[str, Any]:
    """The day's entries, totals vs targets, remaining, percentages, status and flags."""
    tz = _tz(user)
    local_now = now_local(tz)
    day = day or local_now.date()
    entries = await entries_for_day(db, user, day)
    totals = aggregate(e.totals for e in entries)
    targets = compute_targets(user.profile).nutrients
    return {
        "date": day,
        "health_status": daily_status(totals, targets, has_entries=bool(entries), day=day, now_local=local_now),
        "entries": [to_out(e) for e in entries],
        "totals": totals,
        "targets": targets,
        "remaining": remaining(totals, targets),
        "percent_of_target": percent_of_target(totals, targets),
        "status_flags": daily_status_flags(totals, targets, day=day, now_local=local_now) if entries else [],
    }


def _streak(logged_days: set[date], today: date) -> int:
    """Consecutive logged days ending today (or yesterday, if today has nothing logged yet)."""
    cursor = today if today in logged_days else today - timedelta(days=1)
    streak = 0
    while cursor in logged_days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


async def summary(db: AsyncSession, user: User, days: int) -> dict[str, Any]:
    """Per-day totals (zero-filled), averages over logged days, streak and top foods."""
    today = today_for(user)
    start = today - timedelta(days=days - 1)
    rows = list(
        await db.scalars(
            select(IntakeEntry).where(
                IntakeEntry.user_id == user.id, IntakeEntry.local_date >= start, IntakeEntry.local_date <= today
            )
        )
    )
    by_day: dict[date, list[IntakeEntry]] = {}
    foods: Counter[str] = Counter()
    display: dict[str, str] = {}
    for e in rows:
        by_day.setdefault(e.local_date, []).append(e)
        for it in e.items or []:
            key = (it.get("name") or "").strip().lower()
            if key:
                foods[key] += 1
                display.setdefault(key, it["name"].strip())

    target_kcal = compute_targets(user.profile).nutrients["calories"]
    out_days = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        day_totals = aggregate(e.totals for e in by_day.get(d, []))
        out_days.append(
            {
                "date": d,
                "totals": day_totals,
                "calorie_percent": round(100 * day_totals["calories"] / target_kcal) if target_kcal else 0,
                "entries": len(by_day.get(d, [])),
            }
        )

    logged = [d for d in out_days if d["entries"]]
    averages = round_nutrients(
        {k: sum(d["totals"][k] for d in logged) / len(logged) for k in NUTRIENT_KEYS} if logged else {}
    )
    # A streak can extend beyond the window, so look further back for it.
    streak_rows = await db.scalars(
        select(IntakeEntry.local_date)
        .distinct()
        .where(IntakeEntry.user_id == user.id, IntakeEntry.local_date >= today - timedelta(days=366))
    )
    return {
        "days": out_days,
        "averages": averages,
        "days_logged": len(logged),
        "streak_days_logged": _streak(set(streak_rows), today),
        "top_foods": [{"name": display[k], "count": c} for k, c in foods.most_common(TOP_FOODS_LIMIT)],
    }
