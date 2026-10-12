"""Seed or refresh the foods reference table from app/data/foods_seed.json.

Usage: python scripts/seed_foods.py   (uses DATABASE_URL; run `alembic upgrade head` first for Postgres)
The server also seeds the table on startup when it is empty, so this is only needed to force a refresh
after editing the seed file.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker, init_engine
from app.services import nutrition_db


async def main() -> int:
    init_engine(get_settings().DATABASE_URL)
    try:
        async with get_sessionmaker()() as session:
            written = await nutrition_db.seed(session)
        print(f"Seeded/updated {written} foods.")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
