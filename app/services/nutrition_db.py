"""Ground nutrition in the reference `foods` table.

Gemini estimates each item's name and weight in grams; this module replaces the per-item nutrients with values
computed from the table (per-100 g × grams), keyed by the item's canonical_name or an alias. Foods not in the
table keep Gemini's own estimate. This is the "approximate but meaningful" the brief asks for: portions from
vision, nutrient density from a curated database (IFCT 2017 / USDA)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Food, FoodAlias
from app.services.nutrition import canonicalize, round_nutrients, scale

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "foods_seed.json"

TABLE = "table"
ESTIMATE = "estimate"


def load_seed() -> list[dict[str, Any]]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


async def count(db: AsyncSession) -> int:
    return int(await db.scalar(select(func.count()).select_from(Food)) or 0)


async def _lookup(db: AsyncSession) -> dict[str, Food]:
    """canonical_name and every alias → Food (one small query; the table is reference data)."""
    foods = (await db.scalars(select(Food))).all()
    index: dict[str, Food] = {}
    for food in foods:
        index[food.canonical_name] = food
        for alias in food.aliases:
            index.setdefault(alias.alias, food)
    return index


def _match(index: dict[str, Food], item: dict[str, Any]) -> Food | None:
    for key in (item.get("canonical_name"), canonicalize(item.get("name", ""))):
        if key and key in index:
            return index[key]
    return None


async def ground_items(db: AsyncSession, items: list[dict[str, Any]]) -> None:
    """Replace each item's nutrients with table values where the food is known; mark `nutrition_source`.

    Mutates the item dicts in place. Items keep their Gemini-estimated grams either way."""
    if not items:
        return
    index = await _lookup(db)
    grounded = 0
    for item in items:
        food = _match(index, item)
        if food is None:
            item["nutrition_source"] = ESTIMATE
            continue
        grams = float(item.get("quantity_g") or 0.0)
        item["nutrients_per_100g"] = round_nutrients(food.per_100g)
        item["nutrients"] = round_nutrients(scale(food.per_100g, grams))
        item["nutrition_source"] = TABLE
        grounded += 1
    logger.info("nutrition grounding", extra={"items": len(items), "from_table": grounded})


async def seed(db: AsyncSession, foods: list[dict[str, Any]] | None = None) -> int:
    """Insert or update foods and their aliases from the seed data. Idempotent."""
    foods = foods if foods is not None else load_seed()
    existing = {f.canonical_name: f for f in (await db.scalars(select(Food))).all()}
    seen_aliases = {a.alias: a for a in (await db.scalars(select(FoodAlias))).all()}
    written = 0
    for row in foods:
        cn = row["canonical_name"]
        food = existing.get(cn)
        if food is None:
            food = Food(canonical_name=cn)
            db.add(food)
            existing[cn] = food
        food.display_name = row["display_name"]
        food.per_100g = round_nutrients(row["per_100g"])
        food.serving_g = float(row["serving_g"])
        food.serving_name = row.get("serving_name", "serving")
        food.source = row.get("source", "IFCT 2017")
        food.region = row.get("region", "IN")
        await db.flush()
        for alias in row.get("aliases", []):
            a = canonicalize(alias)
            if a and a != cn and a not in seen_aliases:
                obj = FoodAlias(alias=a, food_id=food.id)
                db.add(obj)
                seen_aliases[a] = obj
        written += 1
    await db.commit()
    logger.info("seeded foods", extra={"foods": written, "aliases": len(seen_aliases)})
    return written
