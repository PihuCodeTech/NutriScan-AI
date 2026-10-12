"""The foods table grounds nutrients: known dishes use curated per-100 g values, unknown ones keep the estimate."""

from __future__ import annotations

import pytest

from app.services import nutrition_db
from app.services.nutrition import NUTRIENT_KEYS


@pytest.fixture
async def seeded(settings):
    """A DB session with the foods table seeded (the app seeds on startup; here we do it directly)."""
    from app.db.session import dispose_engine, get_sessionmaker, init_engine

    init_engine(settings.DATABASE_URL)
    from app.db.base import Base
    from app.db.session import get_engine

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with get_sessionmaker()() as session:
        await nutrition_db.seed(session)
        yield session
    await dispose_engine()


async def test_seed_is_idempotent(seeded):
    before = await nutrition_db.count(seeded)
    assert before > 0
    await nutrition_db.seed(seeded)
    assert await nutrition_db.count(seeded) == before  # no duplicates on a second run


async def test_known_food_uses_table_values(seeded):
    # roti is in the seed at 297 kcal / 100 g; 80 g → 237.6
    items = [{"name": "Roti", "canonical_name": "roti", "quantity_g": 80, "nutrients": {"calories": 999}}]
    await nutrition_db.ground_items(seeded, items)
    assert items[0]["nutrition_source"] == "table"
    assert items[0]["nutrients"]["calories"] == pytest.approx(237.6, abs=0.5)
    assert set(items[0]["nutrients"]) == set(NUTRIENT_KEYS)


async def test_alias_is_matched(seeded):
    # "chapati" is an alias of roti
    items = [{"name": "Chapati", "canonical_name": "chapati", "quantity_g": 100, "nutrients": {"calories": 0}}]
    await nutrition_db.ground_items(seeded, items)
    assert items[0]["nutrition_source"] == "table"
    assert items[0]["nutrients"]["calories"] == pytest.approx(297, abs=1)


async def test_unknown_food_keeps_estimate(seeded):
    original = {
        "calories": 123,
        "protein_g": 5,
        "carbohydrates_g": 10,
        "fat_g": 4,
        "saturated_fat_g": 1,
        "fiber_g": 2,
        "sugar_g": 1,
        "sodium_mg": 50,
    }
    items = [{"name": "Alien Stew", "canonical_name": "zzz_not_a_food", "quantity_g": 200, "nutrients": dict(original)}]
    await nutrition_db.ground_items(seeded, items)
    assert items[0]["nutrition_source"] == "estimate"
    assert items[0]["nutrients"] == original  # untouched
