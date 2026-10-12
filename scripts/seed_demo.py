"""Create a demo user (demo@nutriscan.app / demo12345) with a filled profile and 3 days of intake.

Usage: python scripts/seed_demo.py   (uses DATABASE_URL; run `alembic upgrade head` first for Postgres)
Idempotent: re-running resets the demo user's intake entries.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select

from app.core.config import get_settings
from app.db import models  # noqa: F401
from app.db.base import Base
from app.db.models import IntakeEntry, User
from app.db.session import dispose_engine, get_engine, get_sessionmaker, init_engine
from app.schemas.user import ProfileUpdate
from app.services import intake_service, user_service
from app.utils.timeutil import get_tz, now_local

DEMO_EMAIL = "demo@nutriscan.app"
DEMO_PASSWORD = "demo12345"


def n(cal: float, p: float, c: float, f: float, sat: float, fib: float, sug: float, na: float) -> dict[str, float]:
    return {
        "calories": cal,
        "protein_g": p,
        "carbohydrates_g": c,
        "fat_g": f,
        "saturated_fat_g": sat,
        "fiber_g": fib,
        "sugar_g": sug,
        "sodium_mg": na,
    }


FOODS = {
    "poha": ("Poha", 180, n(270, 5, 45, 8.3, 1.2, 2.3, 2.3, 450)),
    "chai": ("Masala Chai", 150, n(72, 2.3, 10.5, 2.4, 1.5, 0, 9, 30)),
    "roti": ("Roti", 80, n(211, 6.8, 36.8, 4.2, 0.8, 5.2, 1.2, 280)),
    "dal": ("Dal Tadka", 150, n(165, 9, 21, 5.1, 0.9, 5.3, 1.5, 420)),
    "rice": ("Steamed Rice", 150, n(195, 4, 42.8, 0.5, 0.1, 0.6, 0.1, 3)),
    "rajma": ("Rajma", 150, n(215, 10.5, 30, 6, 1, 9, 1.5, 480)),
    "curd": ("Curd", 100, n(61, 3.5, 4.7, 3.3, 2.1, 0, 4.7, 46)),
    "samosa": ("Samosa", 60, n(181, 3, 19.2, 10.2, 2.4, 1.5, 0.9, 252)),
    "maggi": ("Masala Maggi", 250, n(350, 8.8, 47.5, 13.8, 6.3, 2, 2, 1200)),
    "egg": ("Boiled Egg", 100, n(143, 12.6, 0.7, 9.5, 3.1, 0, 0.4, 142)),
    "banana": ("Banana", 120, n(107, 1.3, 27.4, 0.4, 0.1, 3.1, 14.7, 1)),
    "paneer": ("Paneer Bhurji", 150, n(330, 19.5, 9, 24, 12, 1.5, 3, 520)),
}

DAYS = [  # (days ago, meal_type, hour, name, [food keys])
    (2, "breakfast", 8, "Hostel breakfast", ["poha", "chai"]),
    (2, "lunch", 13, "Mess lunch", ["roti", "dal", "rice", "curd"]),
    (2, "snack", 17, "Canteen snack", ["samosa", "chai"]),
    (2, "dinner", 21, "Late-night Maggi", ["maggi"]),
    (1, "breakfast", 8, "Eggs and banana", ["egg", "banana"]),
    (1, "lunch", 13, "Rajma chawal", ["rajma", "rice", "curd"]),
    (1, "dinner", 20, "Paneer and roti", ["paneer", "roti"]),
    (0, "breakfast", 8, "Poha and chai", ["poha", "chai"]),
    (0, "lunch", 13, "Mess thali", ["roti", "dal", "rice"]),
]


async def main() -> None:
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    if settings.DATABASE_URL.startswith("sqlite"):
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = await user_service.register(db, email=DEMO_EMAIL, password=DEMO_PASSWORD, name="Demo Student")
            print(f"created {DEMO_EMAIL}")
        else:
            print(f"{DEMO_EMAIL} exists — resetting intake")
        await user_service.update_profile(
            db,
            user,
            ProfileUpdate(
                age=20,
                sex="male",
                height_cm=172,
                weight_kg=64,
                activity_level="light",
                goal="gain",
                diet_type="eggetarian",
                allergies=["peanuts"],
                conditions=[],
                country="IN",
                timezone="Asia/Kolkata",
            ),
        )
        await db.execute(delete(IntakeEntry).where(IntakeEntry.user_id == user.id))
        tz = get_tz(user.profile.timezone)
        today = now_local(tz).date()
        for days_ago, meal_type, hour, name, keys in DAYS:
            eaten = datetime.combine(today - timedelta(days=days_ago), time(hour, 0), tzinfo=tz)
            if eaten > now_local(tz):
                continue  # don't log meals in the future
            items = [
                {"name": FOODS[k][0], "quantity_g": FOODS[k][1], "nutrients": FOODS[k][2], "source": "user_added"}
                for k in keys
            ]
            db.add(
                intake_service.build_entry(
                    user, source="manual", name=name, meal_type=meal_type, eaten_at=eaten, items=items
                )
            )
        await db.commit()
        count = len(list(await db.scalars(select(IntakeEntry.id).where(IntakeEntry.user_id == user.id))))
        print(f"seeded {count} intake entries over 3 days · login: {DEMO_EMAIL} / {DEMO_PASSWORD}")
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
