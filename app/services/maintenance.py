"""Housekeeping: delete throw-away guest accounts (and their photos) after a retention window, and photos
that no database row references any more.

Guest accounts are created by POST /auth/guest for people who don't sign up; they accumulate forever otherwise.
This removes guests older than `retention_days` together with their uploaded images. Row deletion cascades to
profiles, scans, scan_items, intake, chat and insights via the FK `ondelete=CASCADE`."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.db.models import ChatMessage, ChatSession, Scan, User
from app.services.storage import Storage
from app.services.user_service import GUEST_EMAIL_DOMAIN

logger = logging.getLogger(__name__)


async def cleanup_guests(db: AsyncSession, storage: Storage, retention_days: int) -> int:
    """Delete guest accounts older than `retention_days`. Returns how many were removed."""
    cutoff = utcnow() - timedelta(days=retention_days)
    guest_ids = list(
        await db.scalars(
            select(User.id).where(
                User.email.like(f"%@{GUEST_EMAIL_DOMAIN}"),
                User.created_at < cutoff,
            )
        )
    )
    if not guest_ids:
        return 0

    # Remove image files first (DB cascade handles the rows).
    paths = list(await db.scalars(select(Scan.image_path).where(Scan.user_id.in_(guest_ids))))
    paths += list(
        await db.scalars(
            select(ChatMessage.image_path)
            .join(ChatSession, ChatMessage.session_id == ChatSession.id)
            .where(ChatMessage.image_path.is_not(None), ChatSession.user_id.in_(guest_ids))
        )
    )
    for path in paths:
        if path:
            await storage.delete(path)

    for user in await db.scalars(select(User).where(User.id.in_(guest_ids))):
        await db.delete(user)
    await db.commit()
    logger.info("guest cleanup", extra={"removed": len(guest_ids)})
    return len(guest_ids)


# A photo is written a moment before the row that references it is committed: leave recent files alone.
ORPHAN_MIN_AGE_S = 24 * 3600


async def find_orphan_uploads(db: AsyncSession, storage: Storage, min_age_s: float = ORPHAN_MIN_AGE_S) -> list[str]:
    """Stored photos older than `min_age_s` that no scan or chat message references.

    Only meaningful when `db` is the database this storage folder belongs to: pointed at another database
    (say a local SQLite file sharing ./storage/uploads with Supabase), every photo looks orphaned."""
    files = await storage.list_files(older_than_s=min_age_s)
    if not files:
        return []
    referenced = set(await db.scalars(select(Scan.image_path)))
    referenced |= set(await db.scalars(select(ChatMessage.image_path).where(ChatMessage.image_path.is_not(None))))
    return [f for f in files if f not in referenced]


async def sweep_orphan_uploads(db: AsyncSession, storage: Storage, min_age_s: float = ORPHAN_MIN_AGE_S) -> int:
    """Delete stored photos that no row references (see `find_orphan_uploads`). Returns how many were removed."""
    orphans = await find_orphan_uploads(db, storage, min_age_s)
    for path in orphans:
        await storage.delete(path)
    logger.info("orphan upload sweep", extra={"removed": len(orphans)})
    return len(orphans)
