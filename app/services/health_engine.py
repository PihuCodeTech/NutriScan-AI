"""Deterministic health logic: daily targets, meal score + flags, and daily status.

Targets use Mifflin-St Jeor BMR × activity factor ± a goal adjustment, never below a safe calorie floor.
Nothing here calls an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from app.core.config import DISCLAIMER
from app.services.nutrition import NUTRIENT_KEYS, Nutrients, coerce, round_nutrients

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
GOAL_ADJUST = {"lose": -400, "maintain": 0, "gain": 300}
MEAL_SHARES = {"breakfast": 0.25, "lunch": 0.35, "dinner": 0.30, "snack": 0.10}
# Used when the meal type is unknown, so the same plate scores the same regardless of the time of day.
NEUTRAL_SHARE = 1 / 3
CALORIE_FLOOR_MIN = 1200.0

GOAL_NUTRIENTS = ("calories", "protein_g", "carbohydrates_g", "fat_g", "fiber_g")
LIMIT_NUTRIENTS = ("saturated_fat_g", "sugar_g", "sodium_mg")

DEFAULT_TARGETS: Nutrients = {
    "calories": 2000.0,
    "protein_g": 50.0,
    "carbohydrates_g": 275.0,
    "fat_g": 67.0,
    "saturated_fat_g": 22.0,
    "fiber_g": 30.0,
    "sugar_g": 50.0,
    "sodium_mg": 2000.0,
}

# (min_score, label, color)
HEALTH_LABELS = ((75, "good", "green"), (50, "moderate", "amber"), (0, "needs_attention", "red"))

FLAG_MESSAGES = {
    "sodium_mg": "High in salt for one meal",
    "sugar_g": "Sugary",
    "saturated_fat_g": "High in saturated fat",
    "calories": "Heavy on calories for a {meal_type}",
    "fat_g": "High in fat",
    "protein_g": "Low in protein",
    "fiber_g": "Low in fibre",
}


@dataclass(frozen=True)
class Targets:
    nutrients: Nutrients
    basis: str  # "profile" | "default"
    bmr: float | None = None
    tdee: float | None = None

    def explanation(self) -> str:
        if self.basis == "default":
            return (
                "Standard reference values (2000 kcal). Complete your profile (age, sex, height, weight, "
                "activity, goal) for personalised targets."
            )
        return (
            f"Mifflin–St Jeor BMR {self.bmr:.0f} kcal × activity factor = TDEE {self.tdee:.0f} kcal, adjusted "
            "for your goal (never below max(1200, BMR)). Protein by body weight; fat 30% and saturated fat "
            "10% of calories; fibre 15 g per 1000 kcal; sugar ≤10% of calories; sodium ≤2000 mg."
        )


def _profile_value(profile: Any, key: str) -> Any:
    if profile is None:
        return None
    if isinstance(profile, dict):
        return profile.get(key)
    return getattr(profile, key, None)


def bmr_mifflin(sex: str, weight_kg: float, height_cm: float, age: int) -> float:
    """Mifflin–St Jeor BMR; 'other' uses the mean of the male and female equations."""
    base = 10 * weight_kg + 6.25 * height_cm - 5 * age
    if sex == "male":
        return base + 5
    if sex == "female":
        return base - 161
    return base - 78  # mean of +5 and −161


def compute_targets(profile: Any) -> Targets:
    """Daily targets from a profile (ORM object or dict); defaults if the profile is incomplete."""
    fields = ("age", "sex", "height_cm", "weight_kg", "activity_level", "goal")
    values = {f: _profile_value(profile, f) for f in fields}
    if any(v is None for v in values.values()):
        return Targets(nutrients=dict(DEFAULT_TARGETS), basis="default")

    bmr = bmr_mifflin(values["sex"], float(values["weight_kg"]), float(values["height_cm"]), int(values["age"]))
    tdee = bmr * ACTIVITY_FACTORS[values["activity_level"]]
    kcal = tdee + GOAL_ADJUST[values["goal"]]
    kcal = max(kcal, max(CALORIE_FLOOR_MIN, bmr))
    kcal = float(round(kcal / 10.0) * 10)

    weight = float(values["weight_kg"])
    protein = weight * (1.2 if values["goal"] in {"lose", "gain"} else 1.0)
    fat = 0.30 * kcal / 9
    carbs = max((kcal - 4 * protein - 9 * fat) / 4, 0.0)
    nutrients = {
        "calories": kcal,
        "protein_g": protein,
        "carbohydrates_g": carbs,
        "fat_g": fat,
        "saturated_fat_g": 0.10 * kcal / 9,
        "fiber_g": 15 * kcal / 1000,
        "sugar_g": 0.10 * kcal / 4,
        "sodium_mg": 2000.0,
    }
    return Targets(nutrients=round_nutrients(nutrients), basis="profile", bmr=round(bmr, 2), tdee=round(tdee, 1))


def health_label(score: int) -> tuple[str, str]:
    """(label, color) for a 0–100 score."""
    for threshold, label, color in HEALTH_LABELS:
        if score >= threshold:
            return label, color
    return "needs_attention", "red"


def _ratio(value: float, target: float) -> float:
    return value / target if target > 0 else 0.0


def _flag(nutrient: str, level: str, value: float, meal_target: float, meal_type: str) -> dict[str, Any]:
    whole = nutrient in ("calories", "sodium_mg")
    return {
        "nutrient": nutrient,
        "level": level,
        "value": float(round(value)) if whole else round(value, 1),
        "meal_target": float(round(meal_target)) if whole else round(meal_target, 1),
        "message": FLAG_MESSAGES[nutrient].format(meal_type=meal_type),
    }


def score_meal(
    totals: dict[str, Any], daily_targets: dict[str, Any], meal_type: str | None, tips: list[str] | None = None
) -> dict[str, Any]:
    """Meal score 0–100 with flags. Returns a `Health` dict (tips passed through).

    When `meal_type` is None or not a known type, a neutral one-third-of-day share is used, so a plate is not
    scored more harshly just because it was scanned at a snack time of day."""
    t = coerce(totals)
    share = MEAL_SHARES.get(meal_type or "", NEUTRAL_SHARE)
    meal_target = {k: v * share for k, v in coerce(daily_targets).items()}
    r = {k: _ratio(t[k], meal_target[k]) for k in NUTRIENT_KEYS}
    label_type = meal_type if meal_type in MEAL_SHARES else "meal"
    snack = meal_type == "snack"
    score = 100.0
    flags: list[dict[str, Any]] = []

    def over(nutrient: str, threshold: float, cap: float, slope: float) -> None:
        nonlocal score
        if r[nutrient] > threshold:
            score -= min(cap, slope * (r[nutrient] - threshold))
            flags.append(_flag(nutrient, "high", t[nutrient], meal_target[nutrient], label_type))

    over("sodium_mg", 1.0, 25, 25)
    over("sugar_g", 1.0, 20, 20)
    over("saturated_fat_g", 1.0, 15, 15)
    over("calories", 1.25, 15, 20)
    over("fat_g", 1.3, 10, 10)

    factor = 0.5 if snack else 1.0
    if r["protein_g"] < 0.6:
        score -= 15 * factor
        flags.append(_flag("protein_g", "low", t["protein_g"], meal_target["protein_g"], label_type))
    elif r["protein_g"] < 0.9:
        score -= 7 * factor
    if r["fiber_g"] < 0.5:
        score -= 10 * factor
        flags.append(_flag("fiber_g", "low", t["fiber_g"], meal_target["fiber_g"], label_type))
    elif r["fiber_g"] < 0.8:
        score -= 5 * factor

    final = round(min(100.0, max(0.0, score)))
    label, color = health_label(final)
    return {
        "score": final,
        "label": label,
        "color": color,
        "flags": flags,
        "tips": list(tips or []),
        "disclaimer": DISCLAIMER,
    }


def percent_of_target(totals: dict[str, Any], targets: dict[str, Any]) -> dict[str, int]:
    t, g = coerce(totals), coerce(targets)
    return {k: round(100 * t[k] / g[k]) if g[k] > 0 else 0 for k in NUTRIENT_KEYS}


def remaining(totals: dict[str, Any], targets: dict[str, Any]) -> dict[str, float]:
    """Goal nutrients: max(target − total, 0). Limit nutrients: target − total (may be negative)."""
    t, g = coerce(totals), coerce(targets)
    out = {}
    for k in NUTRIENT_KEYS:
        diff = g[k] - t[k]
        out[k] = max(diff, 0.0) if k in GOAL_NUTRIENTS else diff
    return round_nutrients(out)


def daily_status(
    totals: dict[str, Any], targets: dict[str, Any], *, has_entries: bool, day: date, now_local: datetime
) -> str:
    """Daily status: `no_data` | `over` | `under` | `on_track`."""
    if not has_entries:
        return "no_data"
    pct = {k: (coerce(totals)[k] / v if v > 0 else 0.0) for k, v in coerce(targets).items()}
    if pct["calories"] > 1.10 or any(pct[k] > 1.0 for k in LIMIT_NUTRIENTS):
        return "over"
    day_over = day < now_local.date() or now_local.hour >= 20
    if pct["calories"] < 0.85 and day_over:
        return "under"
    return "on_track"


def daily_status_flags(
    totals: dict[str, Any], targets: dict[str, Any], *, day: date, now_local: datetime
) -> list[dict[str, Any]]:
    """Chips for the dashboard: limit nutrients over 100%, calories over 110%, and (late) low goals."""
    pct = percent_of_target(totals, targets)
    flags: list[dict[str, Any]] = []
    names = {"saturated_fat_g": "saturated fat", "sugar_g": "sugar", "sodium_mg": "salt"}
    for k in LIMIT_NUTRIENTS:
        if pct[k] > 100:
            flags.append(
                {"nutrient": k, "level": "high", "percent": pct[k], "message": f"Over today's {names[k]} limit"}
            )
    if pct["calories"] > 110:
        flags.append(
            {
                "nutrient": "calories",
                "level": "high",
                "percent": pct["calories"],
                "message": "Above today's calorie target",
            }
        )
    day_over = day < now_local.date() or now_local.hour >= 20
    if day_over and pct["calories"] > 0:
        if pct["calories"] < 85:
            flags.append(
                {
                    "nutrient": "calories",
                    "level": "low",
                    "percent": pct["calories"],
                    "message": "Below today's calorie target",
                }
            )
        if pct["protein_g"] < 60:
            flags.append(
                {
                    "nutrient": "protein_g",
                    "level": "low",
                    "percent": pct["protein_g"],
                    "message": "Protein was low today",
                }
            )
        if pct["fiber_g"] < 50:
            flags.append(
                {"nutrient": "fiber_g", "level": "low", "percent": pct["fiber_g"], "message": "Fibre was low today"}
            )
    return flags
