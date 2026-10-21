"""Async engine, session factory and the `get_db` dependency."""

from __future__ import annotations

import asyncio
import logging
import ssl
import time
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_fks(dbapi_conn: Any, _: Any) -> None:
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}

# Supabase's pooler presents a chain signed by Supabase's own root CA, which is not in the system trust store.
_SUPABASE_CA = PROJECT_ROOT / "certs" / "supabase-ca.crt"


def _tls_context() -> ssl.SSLContext:
    """Verified TLS (certificate + hostname): the system CAs plus the bundled Supabase root CA."""
    ctx = ssl.create_default_context()
    if _SUPABASE_CA.is_file():
        ctx.load_verify_locations(cafile=str(_SUPABASE_CA))
    return ctx


# Connections kept open and exercised by `keep_warm`, so requests never pay for opening one.
WARM_CONNECTIONS = 5  # = pool_size: the web app sends ~5 requests at once after sign-in
KEEPALIVE_INTERVAL_S = 60.0
# Opening a connection to a far-away Supabase region measured ~8 s (TCP + TLS + auth + driver setup), so allow
# for that, but fail instead of hanging forever when the database is down or the project is paused.
CONNECT_TIMEOUT_S = 20
POOL_TIMEOUT_S = 20


def _engine_kwargs(url: str) -> dict[str, Any]:
    """Driver-specific engine settings. Supabase (managed Postgres over the Supavisor pooler) needs TLS and
    no prepared-statement caching (transaction mode, port 6543, can't keep them). Connections are kept in a
    small pool: opening one costs many network round trips, seconds on a far-away region. `keep_warm` pings
    the idle ones every minute, so Supavisor never drops them for idleness and a dead one is replaced in the
    background rather than on a user's request. `pool_recycle` is by connection *age*, so it is kept long.
    SSL is used automatically for remote hosts (Supabase) and skipped for a local Postgres."""
    if url.startswith("sqlite"):
        return {"connect_args": {"timeout": 30}}
    if "+asyncpg" in url or url.startswith("postgresql"):
        from sqlalchemy.engine import make_url

        host = (make_url(url).host or "").lower()
        connect_args: dict[str, Any] = {"statement_cache_size": 0, "timeout": CONNECT_TIMEOUT_S}
        if host not in _LOCAL_HOSTS:  # Supabase and other remote Postgres require TLS
            connect_args["ssl"] = _tls_context()
        return {
            "pool_size": 5,
            "max_overflow": 5,
            "pool_recycle": 1800,
            "pool_timeout": POOL_TIMEOUT_S,
            "connect_args": connect_args,
        }
    return {"pool_pre_ping": True}


def is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


async def _ping(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_database(timeout_s: float = 5.0) -> float:
    """Run `SELECT 1` on a pooled connection within `timeout_s`. Returns the seconds taken; raises on failure."""
    started = time.perf_counter()
    await asyncio.wait_for(_ping(get_engine()), timeout=timeout_s)
    return time.perf_counter() - started


def pool_stats() -> tuple[int, int] | None:
    """(checked out, pool size) of the connection pool, or None for SQLite / pools without those numbers."""
    pool = get_engine().pool
    if not hasattr(pool, "checkedout") or not hasattr(pool, "size"):
        return None
    return pool.checkedout(), pool.size()


async def warm_pool(count: int = WARM_CONNECTIONS) -> int:
    """Open (or touch) up to `count` pooled connections concurrently. Returns how many succeeded.

    The web app fires several requests at once on load; with a cold pool each would open its own connection."""
    engine = get_engine()
    if is_sqlite(str(engine.url)):
        return 0
    pool = engine.pool
    idle = pool.checkedin() if hasattr(pool, "checkedin") else 0
    busy = pool.checkedout() if hasattr(pool, "checkedout") else 0
    n = max(idle, count - busy, 0)
    results = await asyncio.gather(*(_ping(engine) for _ in range(n)), return_exceptions=True)
    failed = [r for r in results if isinstance(r, BaseException)]
    if failed:
        logger.warning("database warm-up failed", extra={"failed": len(failed), "error": type(failed[0]).__name__})
    return n - len(failed)


async def keep_warm(interval_s: float = KEEPALIVE_INTERVAL_S) -> None:
    """Background loop: keep a few connections open and alive. Errors are logged, never raised."""
    while True:
        await asyncio.sleep(interval_s)
        try:
            await warm_pool()
        except Exception as exc:  # never let the loop die
            logger.warning("database keep-alive failed", extra={"error": type(exc).__name__})


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
