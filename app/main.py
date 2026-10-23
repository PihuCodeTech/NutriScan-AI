"""FastAPI app factory: CORS, request logging, error envelope, /media, v1 routes, lifespan."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import metrics as metrics_endpoint
from app.api.deps import build_classifier, build_llm, build_storage
from app.api.v1.router import api_router
from app.core.config import APP_VERSION, ENV_FILE, Settings, get_settings, production_warnings, shell_overrides
from app.core.errors import register_exception_handlers
from app.core.http_guards import BODY_OVERHEAD_BYTES, BodySizeLimitMiddleware, SecurityHeadersMiddleware
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.metrics import metrics
from app.core.rate_limit import limiter
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.session import (
    dispose_engine,
    get_engine,
    get_sessionmaker,
    init_engine,
    is_sqlite,
    keep_warm,
    warm_pool,
)
from app.services import maintenance, nutrition_db
from app.services.monitoring import Monitor

logger = logging.getLogger("app")

DESCRIPTION = """\
Backend for **NutriScan AI** — an AI food nutrition scanner and nutrition chatbot for students living in
hostels or on their own.

* **Scan** a food photo: a transfer-learned classifier (ViT fine-tuned on Food-101) gives hints, Gemini vision
  identifies every item and estimates portions and nutrients, and the backend computes totals and a
  deterministic health score.
* **Chat** with NutriBuddy (Gemini, text + images, function calling over your own data).
* **Track** daily intake, trends and daily insights.

Every response uses the envelope `{success, code, message, data}`. Authenticate with `Authorization: Bearer
<token>` from `/auth/register` or `/auth/login`. *Estimates only — not medical advice.*
"""

TAGS = [
    {"name": "system", "description": "Health check and UI metadata (no auth)."},
    {"name": "auth", "description": "Register and log in (JWT bearer tokens, 7-day expiry)."},
    {"name": "users", "description": "Profile and computed daily targets."},
    {"name": "scans", "description": "Food scanner: upload, view, edit portions, tips, log to intake."},
    {"name": "intake", "description": "Meal logging, daily totals vs targets, multi-day summary."},
    {"name": "insights", "description": "AI-written daily insight over server-computed numbers."},
    {"name": "chat", "description": "NutriBuddy chatbot: sessions, text + image messages, SSE streaming."},
    {"name": "recipes", "description": "Gemini meal ideas from the ingredients you have."},
]


async def _prepare_database(app: FastAPI) -> None:
    """Create tables (dev/test), seed the foods table, clean up old guests, then warm the connection pool.

    Each step is independent and failures are logged, never raised: a slow or unreachable database must not
    stop the server (and the web app) from starting. Requests that need the database fail on their own."""
    settings: Settings = app.state.settings
    started = time.perf_counter()
    if settings.APP_ENV in {"dev", "test"}:
        # Convenience for local runs/tests; production uses `alembic upgrade head`.
        try:
            async with get_engine().begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        except Exception:
            logger.exception("could not create tables; is the database reachable? (check DATABASE_URL)")
            return
    # Load the nutrition reference table (52 Indian/common foods) if it's empty, so scans can ground
    # nutrients in curated per-100 g values instead of trusting the model's numbers. Idempotent and cheap.
    try:
        async with get_sessionmaker()() as session:
            if await nutrition_db.count(session) == 0:
                await nutrition_db.seed(session)
    except Exception:
        logger.exception("could not seed the foods table; scans will fall back to AI estimates")
    await app.state.monitor.run_job("guest_cleanup", lambda: _cleanup_guests(app))
    warm = await warm_pool()
    logger.info(
        "database ready",
        extra={"ms": round((time.perf_counter() - started) * 1000), "warm_connections": warm},
    )


async def _cleanup_guests(app: FastAPI) -> None:
    async with get_sessionmaker()() as session:
        await maintenance.cleanup_guests(session, app.state.storage, app.state.settings.GUEST_RETENTION_DAYS)


async def _sweep_uploads(app: FastAPI) -> None:
    async with get_sessionmaker()() as session:
        await maintenance.sweep_orphan_uploads(session, app.state.storage)


async def _load_classifier(app: FastAPI) -> None:
    await app.state.classifier.load()
    if app.state.classifier.status == "error":  # load() logs the cause and lets scans run without hints
        raise RuntimeError("classifier failed to load")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    init_engine(settings.DATABASE_URL)
    background: list[asyncio.Task[None]] = []
    db_task = asyncio.create_task(_prepare_database(app), name="db-prepare")
    if is_sqlite(settings.DATABASE_URL):
        await db_task  # local file: instant, and tests expect the tables to exist on the first request
    else:
        # Remote Postgres (Supabase) costs ~400 ms per round trip from India: start serving straight away.
        background += [db_task, asyncio.create_task(keep_warm(), name="db-keepalive")]
    # Load the classifier in the background: the first run downloads ~350 MB, and the API (and the web app)
    # must be reachable meanwhile. Until it is ready, scans simply run without classifier hints.
    monitor: Monitor = app.state.monitor
    background += [
        asyncio.create_task(monitor.run_job("classifier_load", lambda: _load_classifier(app)), name="classifier-load"),
        asyncio.create_task(monitor.watch(), name="monitor-watchdog"),
        asyncio.create_task(monitor.sample_loop_lag(), name="monitor-loop-lag"),
        asyncio.create_task(
            monitor.run_every("guest_cleanup", settings.GUEST_CLEANUP_INTERVAL_H * 3600, lambda: _cleanup_guests(app)),
            name="guest-cleanup",
        ),
    ]
    if settings.APP_ENV == "prod":
        # Prod only: a dev machine often points one storage folder at several databases (SQLite, Supabase), and
        # against the wrong one every photo looks orphaned. In dev, use scripts/sweep_uploads.py by hand.
        sweep = monitor.run_every("upload_sweep", settings.GUEST_CLEANUP_INTERVAL_H * 3600, lambda: _sweep_uploads(app))
        background.append(asyncio.create_task(sweep, name="upload-sweep"))
    for task in background:
        task.add_done_callback(monitor.report_crash)
    overrides = shell_overrides()
    if overrides:
        logger.warning(
            "settings from the shell environment override .env",
            extra={"names": overrides, "env_file": str(ENV_FILE)},
        )
    logger.info(
        "startup",
        extra={
            "env": settings.APP_ENV,
            "mock_ai": settings.MOCK_AI,
            "gemini": settings.gemini_status,
            "gemini_mode": "vertex" if settings.GEMINI_USE_VERTEX else "developer",
            "model": settings.GEMINI_MODEL,
            "fallback_model": settings.GEMINI_FALLBACK_MODEL,
            "classifier": app.state.classifier.status,
            "classifier_model": settings.CLASSIFIER_MODEL_ID,
            "env_file": str(ENV_FILE) if ENV_FILE.is_file() else "missing",
            "metrics_endpoint": bool(settings.METRICS_TOKEN),
            "alert_webhook": bool(settings.ALERT_WEBHOOK_URL),
        },
    )
    if settings.APP_ENV == "dev" and app.state.frontend_mounted:
        # Plain lines (not JSON) so the address stands out in the terminal.
        print(
            f"\n  NutriScan web app → {settings.PUBLIC_BASE_URL}/app/   (API docs → {settings.PUBLIC_BASE_URL}/docs)\n",
            flush=True,
        )
    try:
        yield
    finally:
        for task in background:
            if not task.done():
                task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL)
    for warning in production_warnings(settings):
        logger.warning(warning)

    app = FastAPI(
        title="NutriScan AI API",
        version=APP_VERSION,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.llm = build_llm(settings)
    app.state.classifier = build_classifier(settings)
    app.state.storage = build_storage(settings)
    app.state.limiter = limiter
    app.state.monitor = Monitor(settings)
    app.state.monitor.watch_classifier(lambda: app.state.classifier.status)
    metrics.add_collector("app", app.state.monitor.collect)

    register_exception_handlers(app)
    # Added first = innermost: oversized bodies are refused before parsing, and the 413 still gets CORS headers.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_upload_bytes + BODY_OVERHEAD_BYTES)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials="*" not in settings.cors_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)

    Path(settings.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    app.include_router(api_router)
    app.include_router(metrics_endpoint.router)

    # The web frontend (static HTML/JS) is served from the same origin, so no CORS setup is needed.
    frontend = Path(settings.FRONTEND_DIR)
    app.state.frontend_mounted = frontend.is_dir()
    if app.state.frontend_mounted:

        @app.middleware("http")
        async def _no_stale_frontend(request: Request, call_next):  # type: ignore[no-untyped-def]
            # Browsers otherwise cache index.html and the scripts for hours, and keep running an old version
            # of the app after an update. no-cache = always revalidate (cheap 304s via ETag).
            response = await call_next(request)
            if request.url.path == "/app" or request.url.path.startswith("/app/"):
                response.headers["Cache-Control"] = "no-cache"
            return response

        app.mount("/app", StaticFiles(directory=frontend, html=True), name="frontend")

        @app.get("/", include_in_schema=False)
        async def _root() -> RedirectResponse:
            return RedirectResponse("/app/")

    return app


app = create_app()
