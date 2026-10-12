"""Meal ideas from the ingredients the user has (Gemini), respecting diet, allergies and kitchen."""

from __future__ import annotations

from typing import Any

from app.core.config import DISCLAIMER
from app.core.errors import AppError
from app.db.models import User
from app.schemas.recipe import RecipeSuggestIn
from app.services import nutrition
from app.services.llm.gemini_client import LLMClient
from app.services.user_service import user_context

_KITCHEN_RANK = {"none": 0, "kettle": 1, "burner": 2}


async def suggest(user: User, body: RecipeSuggestIn, llm: LLMClient) -> dict[str, Any]:
    """Ask Gemini for meal ideas. Nutrients are sanitised server-side; recipes needing more equipment than
    the user has are dropped."""
    result = await llm.suggest_recipes(
        ingredients=body.ingredients,
        kitchen=body.kitchen,
        count=body.count,
        user_ctx=user_context(user),
        note=body.note,
    )
    meals = []
    for r in result.recipes:
        if _KITCHEN_RANK.get(r.kitchen, 2) > _KITCHEN_RANK[body.kitchen]:
            continue
        steps = [s.strip() for s in r.steps if s and s.strip()]
        meals.append(
            {
                "name": r.name.strip()[:120] or "Meal idea",
                "why": r.why.strip()[:300],
                "time_minutes": max(1, min(int(r.time_minutes or 0) or 15, 240)),
                "kitchen": r.kitchen,
                "ingredients": [i.strip() for i in r.ingredients if i and i.strip()][:20],
                "steps": steps[:10],
                "nutrients": nutrition.round_nutrients(nutrition.sanitize(r.nutrients.model_dump(), context=r.name)),
            }
        )
    if not meals:
        raise AppError(
            "AI_BAD_RESPONSE", "The AI didn't suggest any meal that fits your kitchen. Please try again.", 502
        )
    return {"meals": meals[: body.count], "ai_model": llm.last_model_used, "disclaimer": DISCLAIMER}
