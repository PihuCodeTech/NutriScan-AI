"""Nutrient helpers: sanitising LLM estimates, per-100 g scaling and aggregation."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from typing import Any

logger = logging.getLogger(__name__)

NUTRIENT_KEYS: tuple[str, ...] = (
    "calories",
    "protein_g",
    "carbohydrates_g",
    "fat_g",
    "saturated_fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
)
WHOLE_NUMBER_KEYS = frozenset({"calories", "sodium_mg"})
ATWATER_TOLERANCE = 0.25

Nutrients = dict[str, float]


def zero() -> Nutrients:
    """All nutrient keys set to 0."""
    return dict.fromkeys(NUTRIENT_KEYS, 0.0)


def _num(value: Any) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f and f not in (float("inf"), float("-inf")) else 0.0  # NaN/inf → 0


def coerce(n: Mapping[str, Any] | None) -> Nutrients:
    """Return a dict with exactly the fixed keys (missing/invalid values → 0)."""
    n = n or {}
    return {k: _num(n.get(k)) for k in NUTRIENT_KEYS}


def round_nutrients(n: Mapping[str, Any]) -> Nutrients:
    """Round: calories and sodium to whole numbers, everything else to 1 dp."""
    out: Nutrients = {}
    for k in NUTRIENT_KEYS:
        v = _num(n.get(k))
        out[k] = float(round(v)) if k in WHOLE_NUMBER_KEYS else round(v, 1)
    return out


def atwater_kcal(n: Mapping[str, Any]) -> float:
    return 4 * _num(n.get("protein_g")) + 4 * _num(n.get("carbohydrates_g")) + 9 * _num(n.get("fat_g"))


def sanitize(n: Mapping[str, Any] | None, *, context: str = "") -> Nutrients:
    """Clamp negatives, enforce sub-nutrient ≤ parent, and apply the Atwater calorie check."""
    out = {k: max(0.0, v) for k, v in coerce(n).items()}
    out["saturated_fat_g"] = min(out["saturated_fat_g"], out["fat_g"])
    out["sugar_g"] = min(out["sugar_g"], out["carbohydrates_g"])
    out["fiber_g"] = min(out["fiber_g"], out["carbohydrates_g"])
    k = atwater_kcal(out)
    if abs(out["calories"] - k) / max(k, 1.0) > ATWATER_TOLERANCE:
        logger.warning(
            "atwater correction",
            extra={"item": context, "reported_kcal": out["calories"], "atwater_kcal": round(k, 1)},
        )
        out["calories"] = k
    return out


def per_100g(nutrients: Mapping[str, Any], quantity_g: float) -> Nutrients:
    """Nutrients per 100 g (all zeros if quantity is 0)."""
    n = coerce(nutrients)
    if quantity_g <= 0:
        return zero()
    return {k: round(v * 100.0 / quantity_g, 4) for k, v in n.items()}


def scale(per100: Mapping[str, Any], new_g: float) -> Nutrients:
    """Nutrients for `new_g` grams given per-100 g values (linear), rounded."""
    n = coerce(per100)
    return round_nutrients({k: v * max(new_g, 0.0) / 100.0 for k, v in n.items()})


def aggregate(items: Iterable[Mapping[str, Any]]) -> Nutrients:
    """Field-wise sum of nutrient dicts, then rounded."""
    total = zero()
    for n in items:
        for k, v in coerce(n).items():
            total[k] += v
    return round_nutrients(total)


def canonicalize(name: str) -> str:
    """Lowercase snake_case English-ish key for a food name."""
    slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return slug or "food_item"
