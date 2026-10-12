from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.deps import LLM, CurrentUser
from app.api.v1.docs import AI, AUTH, errors
from app.core.rate_limit import ai_limit, limiter
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.recipe import RecipeSuggestIn, RecipeSuggestOut
from app.services import recipe_service

router = APIRouter(prefix="/recipes", tags=["recipes"])


@router.post(
    "/suggest",
    response_model=Envelope[RecipeSuggestOut],
    summary="Meal ideas from your ingredients",
    description="Gemini suggests 1–5 meals the user can make with what they have, within their kitchen "
    "(`none`, `kettle`, `burner`), diet type and allergies. Nutrients are per serving and sanitised by the server.",
    responses=errors(*AUTH, "VALIDATION_ERROR", *AI),
)
@limiter.limit(ai_limit)
async def suggest(request: Request, body: RecipeSuggestIn, user: CurrentUser, llm: LLM) -> dict:
    return ok(await recipe_service.suggest(user, body, llm), "RECIPES_SUGGESTED", "Meal ideas ready")
