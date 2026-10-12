"""Delete throw-away guest accounts (and their photos) older than GUEST_RETENTION_DAYS.

Usage: python scripts/cleanup_guests.py
Run on a schedule (e.g. a daily cron / scheduled task) in production; the server also runs it once at startup.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.deps import build_storage
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker, init_engine
from app.services import maintenance


async def main() -> int:
    settings = get_settings()
    init_engine(settings.DATABASE_URL)
    try:
        async with get_sessionmaker()() as session:
            removed = await maintenance.cleanup_guests(session, build_storage(settings), settings.GUEST_RETENTION_DAYS)
        print(f"Removed {removed} guest account(s) older than {settings.GUEST_RETENTION_DAYS} days.")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
