import pytest

from app.services.nutrition import (
    NUTRIENT_KEYS,
    aggregate,
    atwater_kcal,
    canonicalize,
    coerce,
    per_100g,
    round_nutrients,
    sanitize,
    scale,
)


def test_coerce_fills_all_keys():
    n = coerce({"calories": "120", "protein_g": None, "junk": 5})
    assert list(n) == list(NUTRIENT_KEYS)
    assert n["calories"] == 120.0 and n["protein_g"] == 0.0


def test_sanitize_clamps_and_caps_sub_nutrients():
    n = sanitize(
        {
            "calories": 100,
            "protein_g": -3,
            "carbohydrates_g": 10,
            "fat_g": 5,
            "saturated_fat_g": 9,
            "fiber_g": 15,
            "sugar_g": 12,
            "sodium_mg": -1,
        }
    )
    assert n["protein_g"] == 0
    assert n["sodium_mg"] == 0
    assert n["saturated_fat_g"] == 5  # ≤ fat
    assert n["sugar_g"] == 10  # ≤ carbs
    assert n["fiber_g"] == 10  # ≤ carbs


def test_atwater_correction():
    # P10 C20 F10 → k = 40 + 80 + 90 = 210. 400 kcal is > 25% off → corrected.
    bad = {"calories": 400, "protein_g": 10, "carbohydrates_g": 20, "fat_g": 10}
    assert sanitize(bad)["calories"] == pytest.approx(210)
    # within tolerance (+20%) → kept
    close = {**bad, "calories": 252}
    assert sanitize(close)["calories"] == 252
    assert atwater_kcal(bad) == 210


def test_per_100g_and_scale_linear():
    nutrients = {"calories": 215, "protein_g": 10.5, "carbohydrates_g": 30, "fat_g": 6, "sodium_mg": 480}
    p = per_100g(nutrients, 150)
    assert p["calories"] == pytest.approx(143.3333, abs=1e-3)
    scaled = scale(p, 300)
    assert scaled["calories"] == 430
    assert scaled["protein_g"] == 21.0
    assert scaled["sodium_mg"] == 960
    half = scale(p, 75)
    assert half["protein_g"] == pytest.approx(5.2, abs=0.1)
    assert per_100g(nutrients, 0) == {k: 0.0 for k in NUTRIENT_KEYS}


def test_aggregate_and_rounding():
    items = [
        {"calories": 100.4, "protein_g": 1.26, "sodium_mg": 10.6},
        {"calories": 200.4, "protein_g": 2.26, "sodium_mg": 20.6},
    ]
    total = aggregate(items)
    assert total["calories"] == 301  # whole number
    assert total["protein_g"] == 3.5  # 1 dp
    assert total["sodium_mg"] == 31
    assert aggregate([]) == {k: 0.0 for k in NUTRIENT_KEYS}
    assert round_nutrients({"fat_g": 1.25})["fat_g"] in (1.2, 1.3)


def test_canonicalize():
    assert canonicalize("Paneer Butter Masala") == "paneer_butter_masala"
    assert canonicalize("  Chole-Bhature!! ") == "chole_bhature"
    assert canonicalize("***") == "food_item"
