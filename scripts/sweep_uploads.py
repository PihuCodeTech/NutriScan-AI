"""List (or delete) uploaded photos that no scan or chat message references, older than a day.

Usage: python scripts/sweep_uploads.py            # dry run: list what would be deleted
       python scripts/sweep_uploads.py --delete   # delete them
Uses DATABASE_URL and STORAGE_DIR: make sure DATABASE_URL is the database these photos belong to, otherwise
every photo looks unreferenced. In production the server runs this sweep every GUEST_CLEANUP_INTERVAL_H hours.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.deps import build_storage
from app.core.config import get_settings
from app.db.session import dispose_engine, get_sessionmaker, init_engine
from app.services import maintenance


async def main(delete: bool) -> int:
    settings = get_settings()
    storage = build_storage(settings)
    init_engine(settings.DATABASE_URL)
    try:
        async with get_sessionmaker()() as session:
            orphans = await maintenance.find_orphan_uploads(session, storage)
            for path in orphans:
                print(path)
            if delete:
                for path in orphans:
                    await storage.delete(path)
                print(f"Deleted {len(orphans)} unreferenced photo(s) from {settings.STORAGE_DIR}.")
            else:
                print(f"{len(orphans)} unreferenced photo(s) in {settings.STORAGE_DIR}. Use --delete to remove them.")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--delete", action="store_true", help="delete the files instead of listing them")
    raise SystemExit(asyncio.run(main(parser.parse_args().delete)))
