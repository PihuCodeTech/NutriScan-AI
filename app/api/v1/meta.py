from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import SettingsDep
from app.core.config import DISCLAIMER
from app.core.responses import ok
from app.schemas.common import Envelope
from app.schemas.meta import MetaOut
from app.services.health_engine import LIMIT_NUTRIENTS, MEAL_SHARES

router = APIRouter(tags=["system"])

_NUTRIENTS = [
    ("calories", "Calories", "kcal", 0),
    ("protein_g", "Protein", "g", 1),
    ("carbohydrates_g", "Carbohydrates", "g", 1),
    ("fat_g", "Fat", "g", 1),
    ("saturated_fat_g", "Saturated fat", "g", 1),
    ("fiber_g", "Fibre", "g", 1),
    ("sugar_g", "Sugar", "g", 1),
    ("sodium_mg", "Sodium", "mg", 0),
]


def _opts(*pairs: tuple[str, str]) -> list[dict[str, str]]:
    return [{"value": v, "label": label} for v, label in pairs]


@router.get(
    "/meta",
    response_model=Envelope[MetaOut],
    summary="Units, labels and enums for the UI",
    description="Nutrient keys with units and labels, meal/diet/activity/goal options, health label "
    "thresholds and colours, the disclaimer and the max upload size. No auth. Use this instead of "
    "hard-coding values in the frontend.",
)
async def meta(settings: SettingsDep) -> dict:
    data = {
        "nutrients": [
            {"key": k, "label": label, "unit": unit, "kind": "limit" if k in LIMIT_NUTRIENTS else "goal", "decimals": d}
            for k, label, unit, d in _NUTRIENTS
        ],
        "meal_types": _opts(("breakfast", "Breakfast"), ("lunch", "Lunch"), ("dinner", "Dinner"), ("snack", "Snack")),
        "diet_types": _opts(
            ("veg", "Vegetarian"), ("eggetarian", "Eggetarian"), ("non_veg", "Non-vegetarian"), ("vegan", "Vegan")
        ),
        "activity_levels": _opts(
            ("sedentary", "Sedentary (little or no exercise)"),
            ("light", "Light (1–3 days/week)"),
            ("moderate", "Moderate (3–5 days/week)"),
            ("active", "Active (6–7 days/week)"),
            ("very_active", "Very active (hard exercise or physical job)"),
        ),
        "goals": _opts(("lose", "Lose weight"), ("maintain", "Maintain"), ("gain", "Gain weight / muscle")),
        "sexes": _opts(("male", "Male"), ("female", "Female"), ("other", "Other / prefer not to say")),
        "health_labels": [
            {"label": "good", "color": "green", "min_score": 75, "max_score": 100, "display": "Good"},
            {"label": "moderate", "color": "amber", "min_score": 50, "max_score": 74, "display": "Moderate"},
            {"label": "needs_attention", "color": "red", "min_score": 0, "max_score": 49, "display": "Needs attention"},
        ],
        "meal_shares": MEAL_SHARES,
        "disclaimer": DISCLAIMER,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "accepted_image_types": ["image/jpeg", "image/png", "image/webp"],
    }
    return ok(data)
