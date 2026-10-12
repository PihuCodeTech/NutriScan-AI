# 02 — Architecture

## Stack
| Concern | Choice |
|---|---|
| Web framework | FastAPI (async) + Uvicorn |
| Validation | Pydantic v2, `pydantic-settings` for config |
| DB | SQLAlchemy 2.0 async ORM + Alembic. SQLite (`aiosqlite`) in dev, PostgreSQL (`asyncpg`) in prod |
| Auth | JWT access tokens (`pyjwt`), passwords hashed with `bcrypt` |
| Image handling | Pillow (validate, EXIF-orient then strip, resize to max 1024 px long side, re-encode JPEG q=85) |
| Classifier | Hugging Face `transformers` image-classification pipeline, model `nateraw/food` (ViT-base fine-tuned from `google/vit-base-patch16-224-in21k` on Food-101, 101 classes, ~89% eval accuracy). CPU, PyTorch |
| LLM / vision | Gemini API via `google-genai` SDK. Default model `gemini-3.8-flash`, fallback `gemini-3.5-flash-lite` |
| Streaming | Server-Sent Events (`sse-starlette` or a `StreamingResponse` with `text/event-stream`) |
| Rate limiting | `slowapi` (in-memory), applied to AI endpoints |
| Testing | `pytest`, `pytest-asyncio`, `httpx.AsyncClient` |
| Lint | `ruff` |
| Packaging | `pyproject.toml` (or `requirements.txt` + `requirements-dev.txt`), Dockerfile, docker-compose (api + postgres) |

## Folder layout (create exactly this)
```
.
├── CLAUDE.md
├── DECISIONS.md                 # choices made during the build
├── README.md
├── .env.example
├── pyproject.toml / requirements*.txt
├── Dockerfile
├── docker-compose.yml
├── alembic.ini
├── alembic/                     # migrations
├── app/
│   ├── main.py                  # app factory, routers, CORS, middleware, exception handlers, lifespan (load classifier)
│   ├── core/
│   │   ├── config.py            # Settings (pydantic-settings)
│   │   ├── security.py          # hashing, JWT create/verify
│   │   ├── responses.py         # envelope helpers: ok(), fail()
│   │   ├── errors.py            # AppError(code, message, status) + handlers
│   │   ├── logging.py           # structured logging, request-id middleware
│   │   └── rate_limit.py
│   ├── db/
│   │   ├── base.py              # DeclarativeBase
│   │   ├── session.py           # async engine + get_db dependency
│   │   └── models/              # user.py, profile.py, scan.py, intake.py, chat.py, insight.py
│   ├── schemas/                 # Pydantic request/response models (the API contract)
│   │   ├── common.py            # Envelope[T], Nutrients, Pagination
│   │   ├── auth.py  user.py  scan.py  intake.py  chat.py  insight.py  meta.py
│   ├── api/
│   │   ├── deps.py              # get_current_user, get_db, get_ai services
│   │   └── v1/
│   │       ├── router.py
│   │       ├── health.py  meta.py  auth.py  users.py  scans.py  intake.py  insights.py  chat.py
│   ├── services/
│   │   ├── images.py            # validate + normalise uploads, save to storage
│   │   ├── storage.py           # LocalStorage (interface allows S3 later)
│   │   ├── classifier.py        # FoodClassifier: load once, predict top-k
│   │   ├── nutrition.py         # aggregation, scaling by grams, nutrient helpers
│   │   ├── health_engine.py     # targets, meal score, flags, daily status
│   │   ├── scan_service.py      # orchestrates the scan pipeline
│   │   ├── intake_service.py
│   │   ├── insight_service.py
│   │   ├── chat/
│   │   │   ├── chat_service.py  # session and message persistence, context building, tool loop
│   │   │   ├── tools.py         # tool declarations + executors
│   │   │   └── context.py       # builds system instruction from profile, intake, scan
│   │   └── llm/
│   │       ├── gemini_client.py # the ONLY place that imports google.genai
│   │       ├── prompts.py       # all prompt templates
│   │       ├── schemas.py       # Pydantic schemas used as Gemini response_schema
│   │       └── mock_client.py   # deterministic fixtures for MOCK_AI=true
│   └── utils/
├── storage/uploads/             # gitignored
├── tests/
│   ├── conftest.py              # test app, in-memory SQLite, MOCK_AI, auth helper
│   ├── fixtures/                # sample images (tiny generated JPEGs are fine), gemini fixture JSON
│   └── test_*.py
├── scripts/
│   ├── smoke_gemini.py          # verifies key + model with one text and one image call
│   └── seed_demo.py             # demo user + a few intake entries
└── ml/                          # OPTIONAL, not executed during build
    ├── README.md
    └── finetune_indian_food.py
```

## Configuration (`app/core/config.py`, mirrored in `.env.example`)
| Var | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod` |
| `DATABASE_URL` | `sqlite+aiosqlite:///./nutriscan.db` | Postgres: `postgresql+asyncpg://...` |
| `JWT_SECRET` | *(required in prod)* | |
| `JWT_EXPIRE_MINUTES` | `10080` | 7 days |
| `CORS_ORIGINS` | `*` | comma-separated |
| `GEMINI_API_KEY` | | from Google AI Studio |
| `GEMINI_MODEL` | `gemini-3.8-flash` | |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | used on 429/5xx/timeout after a retry |
| `GEMINI_TIMEOUT_S` | `30` | |
| `MOCK_AI` | `false` | `true` → mock Gemini + mock classifier |
| `CLASSIFIER_ENABLED` | `true` | if false, the scan skips hints |
| `CLASSIFIER_MODEL_ID` | `nateraw/food` | HF id or local path to a fine-tuned model |
| `CLASSIFIER_TOP_K` | `3` | |
| `MAX_UPLOAD_MB` | `8` | |
| `STORAGE_DIR` | `./storage/uploads` | served read-only at `/media` |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | used to build `image_url` |
| `RATE_LIMIT_AI` | `20/minute` | per user (fallback per IP) |
| `CHAT_HISTORY_TURNS` | `20` | messages sent to Gemini per request |
| `CHAT_MAX_TOOL_ROUNDS` | `4` | |
| `LOG_LEVEL` | `INFO` | |

## Request flows

### A. Food scan — `POST /api/v1/scans`
```
upload → images.validate_and_normalise() → storage.save() → sha256
      → classifier.predict(top_k)                        [threadpool, skipped if disabled/failed]
      → gemini.analyze_food_image(image, hints, profile ctx, description)   [structured JSON]
            ├─ is_food == false → 422 NOT_FOOD (scan row saved with status=rejected)
            └─ items[] with per-item grams + nutrients + confidence
      → nutrition.aggregate(items) → plate totals          [server-side sum]
      → health_engine.score_meal(totals, targets, meal_type) → score, label, flags
      → persist Scan + ScanItems → return ScanResult
```
Gemini tips come back in the **same** call as the analysis, so a scan costs one Gemini round trip. The backend then attaches its own deterministic score and flags alongside those tips. When the user edits items, totals, score and flags are recomputed immediately, and tips are regenerated only on request via `POST /scans/{id}/tips` (see API spec).

### B. Chat message — `POST /api/v1/chat/sessions/{id}/messages`
```
save user msg (+ image) → build context (profile, targets, today's totals, linked scan)
 → history = last N messages → gemini.chat(system, history, new msg [+ image], tools)
 → while response has function_calls and rounds < max: execute tools (scoped to the current user) → send results back
 → save assistant msg (+ tool traces) → return
```
The streaming variant runs the tool loop non-streamed, then streams the final answer as SSE `delta` events.

### C. Describe-to-log — `POST /api/v1/intake/describe`
Text → Gemini (same item schema as scans, text-only) → aggregate → preview, or save directly if `log=true`.

## Error handling
- `AppError(code, message, http_status, details=None)` raised in services. A global handler renders the envelope.
- Pydantic validation errors → 422 `VALIDATION_ERROR` with field details.
- Gemini failures: retry once (exponential backoff), then the fallback model, then 503 `AI_UNAVAILABLE`. **Never** a 500 with a stack trace.
- Classifier failure is non-fatal: log it, continue without hints, set `classifier` to `null` in the response.
