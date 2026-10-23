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


async def test_orphan_sweep_removes_only_old_unreferenced_photos(app, client, settings):
    import os
    import time
    from pathlib import Path

    from app.db.session import get_sessionmaker
    from tests.conftest import create_scan, make_jpeg, register_user

    storage = app.state.storage
    headers = await register_user(client)
    assert (await create_scan(client, headers, make_jpeg())).status_code == 201
    old_orphan = await storage.save(b"old", "jpg")
    new_orphan = await storage.save(b"new", "jpg")
    root = Path(settings.STORAGE_DIR)
    two_days_ago = time.time() - 2 * 86400
    for p in root.rglob("*.jpg"):
        if p.name != Path(new_orphan).name:
            os.utime(p, (two_days_ago, two_days_ago))  # the scan's photo is old too, but referenced

    async with get_sessionmaker()() as db:
        assert await maintenance.find_orphan_uploads(db, storage) == [old_orphan]
        assert await maintenance.sweep_orphan_uploads(db, storage) == 1
    remaining = {p.relative_to(root).as_posix() for p in root.rglob("*.jpg")}
    assert old_orphan not in remaining and new_orphan in remaining and len(remaining) == 2


async def test_scan_photo_deleted_when_saving_the_scan_fails(app, client, settings, monkeypatch):
    from pathlib import Path

    import pytest

    from app.services import scan_service
    from tests.conftest import create_scan, make_jpeg, register_user

    async def broken(*_args, **_kwargs):
        raise ConnectionResetError("database went away")

    monkeypatch.setattr(scan_service, "ground_items", broken)
    headers = await register_user(client)
    with pytest.raises(ConnectionResetError):  # the test transport re-raises what would be a 500
        await create_scan(client, headers, make_jpeg())
    assert not any(p.is_file() for p in Path(settings.STORAGE_DIR).rglob("*"))
