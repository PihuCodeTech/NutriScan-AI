"""Chatbot tools: JSON-schema declarations + executors scoped to the current user."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.models import Scan, User
from app.schemas.common import MEAL_TYPES
from app.services import intake_service, scan_service
from app.services.llm.gemini_client import LLMClient
from app.services.llm.schemas import ToolSpec
from app.services.storage import Storage
from app.services.user_service import targets_out

logger = logging.getLogger(__name__)


@dataclass
class ToolContext:
    db: AsyncSession
    user: User
    llm: LLMClient
    storage: Storage


class ToolError(Exception):
    """Returned to the model as {"error": message} instead of being raised to the user."""


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_user_profile",
        description="Get the user's profile (age, sex, height, weight, activity, goal, diet type, allergies, "
        "conditions) and their computed daily nutrition targets.",
        parameters={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="get_daily_intake",
        description="Get what the user logged on a day: entries (name, meal type, calories), totals, targets, "
        "remaining amounts and status. Defaults to today in the user's timezone.",
        parameters={
            "type": "object",
            "properties": {"date": {"type": "string", "description": "YYYY-MM-DD; omit for today"}},
        },
    ),
    ToolSpec(
        name="get_intake_summary",
        description="Summary of the last N days: per-day calories, averages, logging streak and top foods.",
        parameters={
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 31, "description": "default 7"}},
        },
    ),
    ToolSpec(
        name="get_recent_scans",
        description="The user's most recent food scans (id, meal name, calories, health score, time).",
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 10, "description": "default 5"}},
        },
    ),
    ToolSpec(
        name="get_scan_details",
        description="Full details of one scan: items with grams and nutrients, totals, health score and flags.",
        parameters={
            "type": "object",
            "properties": {"scan_id": {"type": "string"}},
            "required": ["scan_id"],
        },
    ),
    ToolSpec(
        name="estimate_meal",
        description="Estimate nutrition for a meal description such as '2 roti and dal' WITHOUT saving it.",
        parameters={
            "type": "object",
            "properties": {"description": {"type": "string"}},
            "required": ["description"],
        },
    ),
    ToolSpec(
        name="log_meal",
        description="Estimate AND save a meal to the user's intake. Only call when the user explicitly asks "
        "to log/add/save something.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "e.g. '2 roti, dal and a glass of lassi'"},
                "meal_type": {"type": "string", "enum": list(MEAL_TYPES)},
                "eaten_at": {"type": "string", "description": "ISO-8601 time; omit for now"},
            },
            "required": ["description", "meal_type"],
        },
    ),
]

PROGRESS_LABELS = {
    "get_user_profile": "Checking your profile…",
    "get_daily_intake": "Checking today's intake…",
    "get_intake_summary": "Looking at your recent days…",
    "get_recent_scans": "Looking at your recent scans…",
    "get_scan_details": "Opening scan details…",
    "estimate_meal": "Estimating nutrition…",
    "log_meal": "Logging your meal…",
}


def _int_arg(args: dict[str, Any], key: str, default: int, lo: int, hi: int) -> int:
    value = args.get(key, default)
    try:
        return max(lo, min(hi, int(float(value))))
    except (TypeError, ValueError):
        return default


async def _get_user_profile(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    p = ctx.user.profile
    profile = {
        k: getattr(p, k, None)
        for k in (
            "age",
            "sex",
            "height_cm",
            "weight_kg",
            "activity_level",
            "goal",
            "diet_type",
            "allergies",
            "conditions",
            "country",
            "timezone",
        )
    }
    return {"name": ctx.user.name, "profile": profile, "targets": targets_out(p)}, "Checked your profile"


async def _get_daily_intake(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    day: date | None = None
    if args.get("date"):
        try:
            day = date.fromisoformat(str(args["date"])[:10])
        except ValueError as exc:
            raise ToolError("date must be YYYY-MM-DD") from exc
    data = await intake_service.daily(ctx.db, ctx.user, day)
    result = {
        "date": data["date"],
        "status": data["health_status"],
        "entries": [
            {"name": e["name"], "meal_type": e["meal_type"], "calories": e["totals"]["calories"]}
            for e in data["entries"]
        ],
        "totals": data["totals"],
        "targets": data["targets"],
        "remaining": data["remaining"],
        "percent_of_target": data["percent_of_target"],
    }
    return result, f"Checked your intake for {data['date'].isoformat()}"


async def _get_intake_summary(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    days = _int_arg(args, "days", 7, 1, 31)
    data = await intake_service.summary(ctx.db, ctx.user, days)
    result = {
        "days": [
            {"date": d["date"], "calories": d["totals"]["calories"], "calorie_percent": d["calorie_percent"]}
            for d in data["days"]
        ],
        "averages": data["averages"],
        "days_logged": data["days_logged"],
        "streak_days_logged": data["streak_days_logged"],
        "top_foods": data["top_foods"],
    }
    return result, f"Looked at your last {days} days"


async def _get_recent_scans(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    limit = _int_arg(args, "limit", 5, 1, 10)
    rows = await ctx.db.scalars(
        select(Scan)
        .where(Scan.user_id == ctx.user.id, Scan.status == "completed")
        .order_by(Scan.created_at.desc())
        .limit(limit)
    )
    result = [
        {
            "id": s.id,
            "meal_name": s.meal_name,
            "meal_type": s.meal_type,
            "calories": s.totals.get("calories"),
            "score": (s.health or {}).get("score"),
            "created_at": s.created_at,
        }
        for s in rows
    ]
    return {"scans": result}, "Looked at your recent scans"


async def _get_scan_details(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    scan_id = str(args.get("scan_id") or "")
    try:
        scan = await scan_service.get_scan(ctx.db, ctx.user, scan_id)
    except AppError as exc:
        raise ToolError("scan not found") from exc
    health = scan.health or {}
    result = {
        "id": scan.id,
        "meal_name": scan.meal_name,
        "meal_type": scan.meal_type,
        "status": scan.status,
        "items": [{"name": i.name, "quantity_g": i.quantity_g, "nutrients": i.nutrients} for i in scan.items],
        "totals": scan.totals,
        "health": {"score": health.get("score"), "label": health.get("label"), "flags": health.get("flags", [])},
        "logged": bool(scan.logged_intake_id),
    }
    return result, "Opened scan details"


async def _estimate_meal(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    description = str(args.get("description") or "").strip()
    if not description:
        raise ToolError("description is required")
    meal_name, items, totals, _tips = await intake_service.estimate_description(ctx.user, description, ctx.llm)
    result = {
        "meal_name": meal_name,
        "items": [{"name": i["name"], "quantity_g": i["quantity_g"], "nutrients": i["nutrients"]} for i in items],
        "totals": totals,
    }
    return result, "Estimated nutrition"


async def _log_meal(ctx: ToolContext, args: dict[str, Any]) -> tuple[Any, str]:
    description = str(args.get("description") or "").strip()
    meal_type = str(args.get("meal_type") or "").strip().lower()
    if not description:
        raise ToolError("description is required")
    if meal_type not in MEAL_TYPES:
        raise ToolError(f"meal_type must be one of {', '.join(MEAL_TYPES)}")
    eaten_at = None
    if args.get("eaten_at"):
        try:
            eaten_at = datetime.fromisoformat(str(args["eaten_at"]).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ToolError("eaten_at must be an ISO-8601 datetime") from exc
    entry = await intake_service.create_from_chat(
        ctx.db, ctx.user, description=description, meal_type=meal_type, eaten_at=eaten_at, llm=ctx.llm
    )
    result = {
        "entry": {
            "id": entry.id,
            "name": entry.name,
            "meal_type": entry.meal_type,
            "eaten_at": entry.eaten_at,
            "items": [{"name": i["name"], "quantity_g": i["quantity_g"]} for i in entry.items],
            "totals": entry.totals,
        }
    }
    return result, f"Logged {entry.name} to your {entry.meal_type}"


_EXECUTORS: dict[str, Callable[[ToolContext, dict[str, Any]], Awaitable[tuple[Any, str]]]] = {
    "get_user_profile": _get_user_profile,
    "get_daily_intake": _get_daily_intake,
    "get_intake_summary": _get_intake_summary,
    "get_recent_scans": _get_recent_scans,
    "get_scan_details": _get_scan_details,
    "estimate_meal": _estimate_meal,
    "log_meal": _log_meal,
}


async def execute(name: str, args: dict[str, Any], ctx: ToolContext) -> tuple[dict[str, Any], str, bool]:
    """Run a tool. Returns (response-for-model, UI summary, ok). Errors become {"error": ...}."""
    executor = _EXECUTORS.get(name)
    if executor is None:
        return {"error": f"unknown tool {name}"}, f"Unknown tool {name}", False
    try:
        result, summary = await executor(ctx, args or {})
        return {"result": jsonable_encoder(result)}, summary, True
    except ToolError as exc:
        return {"error": str(exc)}, f"Couldn't run {name}", False
    except AppError as exc:
        return {"error": exc.message}, f"Couldn't run {name}", False
    except Exception as exc:
        logger.exception("tool failed", extra={"tool": name})
        await ctx.db.rollback()
        return {"error": f"internal error: {type(exc).__name__}"}, f"Couldn't run {name}", False
