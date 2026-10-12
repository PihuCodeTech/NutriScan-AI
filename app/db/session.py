"""Async engine, session factory and the `get_db` dependency."""

from __future__ import annotations

import ssl
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_fks(dbapi_conn: Any, _: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _engine_kwargs(url: str) -> dict[str, Any]:
    """Driver-specific engine settings. Supabase (managed Postgres over the Supavisor pooler) needs TLS and
    no prepared-statement caching; a connection pooler in front means we let it pool and open per request.
    SSL is used automatically for remote hosts (Supabase) and skipped for a local Postgres."""
    if url.startswith("sqlite"):
        return {"connect_args": {"timeout": 30}}
    if "+asyncpg" in url or url.startswith("postgresql"):
        from sqlalchemy.engine import make_url

        host = (make_url(url).host or "").lower()
        connect_args: dict[str, Any] = {"statement_cache_size": 0}
        if host not in _LOCAL_HOSTS:  # Supabase and other remote Postgres require TLS
            connect_args["ssl"] = ssl.create_default_context()
        return {"poolclass": NullPool, "connect_args": connect_args}
    return {"pool_pre_ping": True}


def init_engine(url: str) -> AsyncEngine:
    """Create (or replace) the global engine and session factory."""
    global _engine, _sessionmaker
    _engine = create_async_engine(url, **_engine_kwargs(url))
    if url.startswith("sqlite"):
        event.listen(_engine.sync_engine, "connect", _enable_sqlite_fks)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        from app.core.config import get_settings

        init_engine(get_settings().DATABASE_URL)
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        get_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request; rolled back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
