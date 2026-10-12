from datetime import date, datetime

import pytest

from app.services.health_engine import (
    DEFAULT_TARGETS,
    bmr_mifflin,
    compute_targets,
    daily_status,
    daily_status_flags,
    health_label,
    percent_of_target,
    remaining,
    score_meal,
)

MALE = {"age": 20, "sex": "male", "height_cm": 175, "weight_kg": 70, "activity_level": "moderate", "goal": "maintain"}


def test_bmr_equations():
    assert bmr_mifflin("male", 70, 175, 20) == pytest.approx(1698.75)
    assert bmr_mifflin("female", 70, 175, 20) == pytest.approx(1532.75)
    assert bmr_mifflin("other", 70, 175, 20) == pytest.approx((1698.75 + 1532.75) / 2)


def test_targets_male_maintain():
    t = compute_targets(MALE)
    assert t.basis == "profile"
    assert t.bmr == pytest.approx(1698.75)
    assert t.tdee == pytest.approx(2633.1, abs=0.1)
    n = t.nutrients
    assert n["calories"] == 2630
    assert n["protein_g"] == 70.0
    assert n["fat_g"] == pytest.approx(round(0.3 * 2630 / 9, 1))
    assert n["saturated_fat_g"] == pytest.approx(round(0.1 * 2630 / 9, 1))
    assert n["carbohydrates_g"] == pytest.approx(round((2630 - 4 * 70 - 9 * (0.3 * 2630 / 9)) / 4, 1))
    assert n["fiber_g"] == pytest.approx(39.45, abs=0.06)
    assert n["sugar_g"] == pytest.approx(round(0.1 * 2630 / 4, 1))
    assert n["sodium_mg"] == 2000


def test_targets_goal_adjustments_and_protein():
    lose = compute_targets({**MALE, "goal": "lose"}).nutrients
    gain = compute_targets({**MALE, "goal": "gain"}).nutrients
    assert lose["calories"] == 2230  # 2633 − 400 → round to 10
    assert gain["calories"] == 2930
    assert lose["protein_g"] == pytest.approx(84.0)
    assert gain["protein_g"] == pytest.approx(84.0)


def test_calorie_floor_respected_for_lose():
    # Small, sedentary female: BMR ≈ 1098, TDEE ≈ 1318, lose → 918 < floor max(1200, BMR) = 1200
    profile = {
        "age": 30,
        "sex": "female",
        "height_cm": 150,
        "weight_kg": 45,
        "activity_level": "sedentary",
        "goal": "lose",
    }
    t = compute_targets(profile)
    assert t.nutrients["calories"] == 1200
    # BMR above 1200: floor is the BMR itself. BMR 1780, TDEE 2136, lose → 1736 < 1780 → 1780.
    heavy = {"age": 30, "sex": "male", "height_cm": 180, "weight_kg": 80, "activity_level": "sedentary", "goal": "lose"}
    th = compute_targets(heavy)
    assert th.bmr == pytest.approx(1780)
    assert th.nutrients["calories"] == 1780


def test_default_targets_when_incomplete():
    for profile in (None, {}, {**MALE, "age": None}, {k: v for k, v in MALE.items() if k != "goal"}):
        t = compute_targets(profile)
        assert t.basis == "default"
        assert t.nutrients == DEFAULT_TARGETS


def test_health_label_boundaries():
    assert health_label(100) == ("good", "green")
    assert health_label(75) == ("good", "green")
    assert health_label(74) == ("moderate", "amber")
    assert health_label(50) == ("moderate", "amber")
    assert health_label(49) == ("needs_attention", "red")
    assert health_label(0) == ("needs_attention", "red")


BALANCED_LUNCH = {
    "calories": 650,
    "protein_g": 25,
    "carbohydrates_g": 85,
    "fat_g": 20,
    "saturated_fat_g": 5,
    "fiber_g": 10,
    "sugar_g": 8,
    "sodium_mg": 600,
}


def test_balanced_meal_scores_good():
    h = score_meal(BALANCED_LUNCH, DEFAULT_TARGETS, "lunch")
    assert h["score"] >= 75
    assert h["label"] == "good" and h["color"] == "green"
    assert h["flags"] == []
    assert h["disclaimer"] == "Estimates only — not medical advice."


def test_high_sodium_penalised_and_flagged():
    salty = {**BALANCED_LUNCH, "sodium_mg": 1400}  # meal target 700 → r = 2 → −25 (capped)
    h = score_meal(salty, DEFAULT_TARGETS, "lunch")
    assert h["score"] == 75
    flag = next(f for f in h["flags"] if f["nutrient"] == "sodium_mg")
    assert flag["level"] == "high"
    assert flag["value"] == 1400
    assert flag["meal_target"] == 700
    assert flag["message"] == "High in salt for one meal"
    slightly = score_meal({**BALANCED_LUNCH, "sodium_mg": 875}, DEFAULT_TARGETS, "lunch")  # r = 1.25 → −6.25
    assert slightly["score"] == 94


def test_low_protein_and_fibre_tiers():
    # protein r < 0.6 → −15 + flag; fibre r < 0.5 → −10 + flag
    h = score_meal({**BALANCED_LUNCH, "protein_g": 5, "fiber_g": 2}, DEFAULT_TARGETS, "lunch")
    assert h["score"] == 75
    assert {f["nutrient"] for f in h["flags"]} == {"protein_g", "fiber_g"}
    assert next(f for f in h["flags"] if f["nutrient"] == "protein_g")["message"] == "Low in protein"
    # middle tiers: penalties but no flags
    target_protein = 50 * 0.35  # 17.5
    target_fiber = 30 * 0.35  # 10.5
    h2 = score_meal(
        {**BALANCED_LUNCH, "protein_g": target_protein * 0.75, "fiber_g": target_fiber * 0.6}, DEFAULT_TARGETS, "lunch"
    )
    assert h2["score"] == 100 - 7 - 5
    assert h2["flags"] == []


def test_snack_penalties_halved():
    snack = {"calories": 150, "protein_g": 0, "carbohydrates_g": 30, "fat_g": 3, "fiber_g": 0, "sodium_mg": 50}
    h = score_meal(snack, DEFAULT_TARGETS, "snack")
    assert h["score"] == round(100 - 7.5 - 5)


def test_calorie_and_fat_penalties():
    heavy = {**BALANCED_LUNCH, "calories": 1050, "fat_g": 35}  # r_cal = 1.5 → −5; r_fat ≈ 1.49 → −1.9
    h = score_meal(heavy, DEFAULT_TARGETS, "lunch")
    assert "calories" in {f["nutrient"] for f in h["flags"]}
    assert "Heavy on calories for a lunch" in {f["message"] for f in h["flags"]}
    assert h["score"] == 93


def test_score_clamped_to_zero():
    awful = {
        "calories": 3000,
        "protein_g": 0,
        "carbohydrates_g": 400,
        "fat_g": 150,
        "saturated_fat_g": 60,
        "fiber_g": 0,
        "sugar_g": 200,
        "sodium_mg": 5000,
    }
    h = score_meal(awful, DEFAULT_TARGETS, "snack")
    assert 0 <= h["score"] < 50
    assert h["label"] == "needs_attention"


def test_daily_status():
    targets = DEFAULT_TARGETS
    today = date(2026, 9, 28)
    morning = datetime(2026, 9, 28, 10, 0)
    night = datetime(2026, 9, 28, 21, 0)
    low = {"calories": 800}
    ok = {"calories": 1900}
    assert daily_status({}, targets, has_entries=False, day=today, now_local=morning) == "no_data"
    assert daily_status(low, targets, has_entries=True, day=today, now_local=morning) == "on_track"
    assert daily_status(low, targets, has_entries=True, day=today, now_local=night) == "under"
    assert daily_status(low, targets, has_entries=True, day=date(2026, 9, 27), now_local=morning) == "under"
    assert daily_status({"calories": 2300}, targets, has_entries=True, day=today, now_local=morning) == "over"
    assert daily_status({**ok, "sodium_mg": 2100}, targets, has_entries=True, day=today, now_local=morning) == "over"
    assert daily_status(ok, targets, has_entries=True, day=today, now_local=night) == "on_track"


def test_remaining_and_percent():
    totals = {"calories": 1500, "protein_g": 60, "sodium_mg": 2500}
    rem = remaining(totals, DEFAULT_TARGETS)
    assert rem["calories"] == 500
    assert rem["protein_g"] == 0  # goal nutrient floors at 0
    assert rem["sodium_mg"] == -500  # limit nutrient may go negative
    pct = percent_of_target(totals, DEFAULT_TARGETS)
    assert pct["calories"] == 75 and pct["protein_g"] == 120 and pct["sodium_mg"] == 125
    assert all(isinstance(v, int) for v in pct.values())


def test_daily_status_flags():
    flags = daily_status_flags(
        {"calories": 1000, "sodium_mg": 2500, "protein_g": 10, "fiber_g": 5},
        DEFAULT_TARGETS,
        day=date(2026, 9, 28),
        now_local=datetime(2026, 9, 28, 21, 0),
    )
    kinds = {(f["nutrient"], f["level"]) for f in flags}
    assert ("sodium_mg", "high") in kinds
    assert ("calories", "low") in kinds
    assert ("protein_g", "low") in kinds
