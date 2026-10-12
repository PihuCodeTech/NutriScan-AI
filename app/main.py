"""FastAPI app factory: CORS, request logging, error envelope, /media, v1 routes, lifespan."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.deps import build_classifier, build_llm, build_storage
from app.api.v1.router import api_router
from app.core.config import APP_VERSION, ENV_FILE, Settings, get_settings, shell_overrides
from app.core.errors import register_exception_handlers
from app.core.logging import RequestContextMiddleware, configure_logging
from app.core.rate_limit import limiter
from app.db import models  # noqa: F401  (registers tables)
from app.db.base import Base
from app.db.session import dispose_engine, get_engine, get_sessionmaker, init_engine
from app.services import maintenance, nutrition_db

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    init_engine(settings.DATABASE_URL)
    if settings.APP_ENV in {"dev", "test"}:
        # Convenience for local runs/tests; production uses `alembic upgrade head`.
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    # Load the nutrition reference table (52 Indian/common foods) if it's empty, so scans can ground
    # nutrients in curated per-100 g values instead of trusting the model's numbers. Idempotent and cheap.
    try:
        async with get_sessionmaker()() as session:
            if await nutrition_db.count(session) == 0:
                await nutrition_db.seed(session)
    except Exception:
        logger.exception("could not seed the foods table; scans will fall back to AI estimates")
    try:
        async with get_sessionmaker()() as session:
            await maintenance.cleanup_guests(session, app.state.storage, settings.GUEST_RETENTION_DAYS)
    except Exception:
        logger.exception("guest cleanup failed")
    # Load the classifier in the background: the first run downloads ~350 MB, and the API (and the web app)
    # must be reachable meanwhile. Until it is ready, scans simply run without classifier hints.
    classifier_task = asyncio.create_task(app.state.classifier.load(), name="classifier-load")
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
        if not classifier_task.done():
            classifier_task.cancel()
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.LOG_LEVEL)

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

    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials="*" not in settings.cors_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    Path(settings.STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    app.include_router(api_router)

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
