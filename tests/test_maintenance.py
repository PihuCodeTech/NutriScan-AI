"""Guest cleanup removes old guest accounts and their photos, and leaves real accounts alone."""

from __future__ import annotations

from datetime import timedelta

from app.db.base import utcnow
from app.db.models import User
from app.services import maintenance, user_service


async def _make_guest(db, *, days_old: int):
    user = await user_service.create_guest(db)
    user.created_at = utcnow() - timedelta(days=days_old)
    await db.commit()
    return user


async def test_old_guests_removed_recent_kept(app):
    from app.db.session import get_sessionmaker

    storage = app.state.storage
    async with get_sessionmaker()() as db:
        old = await _make_guest(db, days_old=10)
        recent = await _make_guest(db, days_old=1)
        real = await user_service.register(db, email="real@example.com", password="password123", name="Real")
        real.created_at = utcnow() - timedelta(days=100)
        await db.commit()
        old_id, recent_id, real_id = old.id, recent.id, real.id

        removed = await maintenance.cleanup_guests(db, storage, retention_days=3)
        assert removed == 1
        assert await db.get(User, old_id) is None
        assert await db.get(User, recent_id) is not None  # within retention
        assert await db.get(User, real_id) is not None  # not a guest


async def test_cleanup_noop_when_none(app):
    from app.db.session import get_sessionmaker

    async with get_sessionmaker()() as db:
        assert await maintenance.cleanup_guests(db, app.state.storage, retention_days=3) == 0
