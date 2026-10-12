"""Builds the per-turn chatbot system instruction from profile, targets, today's intake and a linked scan."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatSession, Scan, User
from app.services import intake_service
from app.services.llm.prompts import CHAT_SYSTEM_TEMPLATE
from app.utils.timeutil import get_tz, now_local


def _fmt_list(values: list[str] | None, empty: str = "none") -> str:
    return ", ".join(values) if values else empty


def targets_short(t: dict[str, Any]) -> str:
    return (
        f"{t['calories']:.0f} kcal, protein {t['protein_g']:.0f} g, carbs {t['carbohydrates_g']:.0f} g, "
        f"fat {t['fat_g']:.0f} g, fibre {t['fiber_g']:.0f} g; limits: sugar ≤{t['sugar_g']:.0f} g, "
        f"sat fat ≤{t['saturated_fat_g']:.0f} g, sodium ≤{t['sodium_mg']:.0f} mg"
    )


def totals_short(t: dict[str, Any]) -> str:
    return (
        f"{t['calories']:.0f} kcal, protein {t['protein_g']:.0f} g, carbs {t['carbohydrates_g']:.0f} g, "
        f"fat {t['fat_g']:.0f} g, fibre {t['fiber_g']:.0f} g, sodium {t['sodium_mg']:.0f} mg"
    )


def scan_block(scan: Scan) -> str:
    if scan.status != "completed":
        return "LINKED MEAL: the linked photo was not recognised as food."
    items = "; ".join(f"{i.name} {i.quantity_g:g} g ({i.nutrients.get('calories', 0):.0f} kcal)" for i in scan.items)
    health = scan.health or {}
    flags = ", ".join(f["message"] for f in health.get("flags", [])) or "none"
    return (
        f"LINKED MEAL (this chat is about this scanned meal): {scan.meal_name} ({scan.meal_type}, scan_id {scan.id})\n"
        f"- Items: {items}\n"
        f"- Totals: {totals_short(scan.totals)}\n"
        f"- Health score: {health.get('score', '?')}/100 ({health.get('label', '?')}); flags: {flags}\n"
        f"- Logged to intake: {'yes' if scan.logged_intake_id else 'no'}"
    )


async def build_chat_system(db: AsyncSession, user: User, session: ChatSession) -> str:
    """System instruction for one chat turn (kept compact, well under ~600 tokens)."""
    profile = user.profile
    tz = get_tz(profile.timezone if profile else None)
    local = now_local(tz)
    today = await intake_service.daily(db, user, local.date())
    meals = "; ".join(f"{e['meal_type']}: {e['name']}" for e in today["entries"]) or "none yet"

    linked = ""
    if session.scan_id:
        scan = await db.scalar(select(Scan).where(Scan.id == session.scan_id, Scan.user_id == user.id))
        if scan is not None:
            linked = scan_block(scan)

    return CHAT_SYSTEM_TEMPLATE.format(
        name=user.name,
        diet_type=(profile.diet_type if profile else None) or "unknown",
        allergies=_fmt_list(profile.allergies if profile else None),
        goal=(profile.goal if profile else None) or "unknown",
        conditions=_fmt_list(profile.conditions if profile else None),
        targets_short=targets_short(today["targets"]),
        date=local.date().isoformat(),
        today_totals_short=totals_short(today["totals"]),
        percent_calories=today["percent_of_target"]["calories"],
        meal_list=meals,
        linked_scan_block=linked,
        local_time=local.strftime("%a %d %b %Y, %H:%M"),
    )
