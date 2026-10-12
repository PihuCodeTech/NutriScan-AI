# 06 — Build Plan (follow in order)

Each milestone ends with: `ruff check . --fix && ruff check .` clean, and `pytest -q` green (with `MOCK_AI=true`). Commit after each milestone if git is initialised: `git commit -m "M<n>: <title>"`.

---

### M0 — Scaffold and tooling
- Create the folder layout from `02_ARCHITECTURE.md`, `pyproject.toml` (or requirements files), `.env.example`, `.gitignore` (`.env`, `*.db`, `storage/`, `__pycache__`, `ml/output/`, `ml/data/`), and `DECISIONS.md`.
- Dependencies: `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `pydantic-settings`, `sqlalchemy>=2`, `aiosqlite`, `asyncpg`, `alembic`, `pyjwt`, `bcrypt`, `python-multipart`, `pillow`, `google-genai`, `transformers`, `torch` (CPU), `slowapi`, `sse-starlette`, `anyio`. Dev: `pytest`, `pytest-asyncio`, `httpx`, `ruff`.
- `app/core/config.py` (Settings), `responses.py` (envelope), `errors.py` (AppError + handlers for AppError, RequestValidationError, HTTPException, generic Exception), `logging.py` (request-id middleware, JSON-ish logs).
- `app/main.py` app factory with CORS, `/media` static mount, v1 router, exception handlers.
- `GET /api/v1/health` and `GET /api/v1/meta`.
- **Accept:** `uvicorn app.main:app` starts; `/docs` loads; tests for health and meta pass.

### M1 — Database and auth
- Async engine and session, all models from `04_DATA_MODEL.md`, first Alembic migration (async env). In `dev`/`test`, `create_all` on startup is allowed as a convenience, but the migration must exist.
- `security.py`: bcrypt hash/verify, JWT create/decode. `deps.get_current_user`.
- `/auth/register`, `/auth/login`, `/users/me`, `PUT /users/me/profile`.
- **Accept:** tests for register → login → me; duplicate email 409; bad password 401; missing token 401; profile partial update.

### M2 — Health engine and targets (pure logic first)
- `nutrition.py` (sanitize, per_100g, scale, aggregate) and `health_engine.py` (targets, meal score, flags, daily status) exactly as specified in §5–6 of `05_AI_PIPELINE.md`.
- `GET /users/me/targets`.
- **Accept:** unit tests with hand-computed cases: male 20 y / 175 cm / 70 kg / moderate / maintain → BMR 1698.75, TDEE ≈ 2633 → 2630 kcal; calorie floor respected for "lose" with a low TDEE; default targets when the profile is incomplete; meal score boundaries (a high-sodium meal is penalised; a balanced meal scores ≥ 75); Atwater correction; scaling by grams.

### M3 — Image handling and classifier
- `images.py`: check content type **and** actually open with Pillow (reject non-images), enforce `MAX_UPLOAD_MB`, EXIF transpose, convert to RGB, resize to max 1024 px, JPEG q=85, sha256. `storage.py` LocalStorage saves to `STORAGE_DIR/YYYY/MM/<uuid>.jpg` and builds `image_url`.
- `classifier.py` with the real HF pipeline plus `MockClassifier`, loaded in `lifespan` in a thread. Status reported in `/health`.
- **Accept:** tests for invalid file → `INVALID_IMAGE`, oversize → `FILE_TOO_LARGE`, valid image normalised; mock classifier used in tests (no downloads).

### M4 — Gemini client and mock client
- `llm/schemas.py`, `llm/prompts.py`, `llm/gemini_client.py` (retry, fallback, timeout, JSON repair), `llm/mock_client.py`, and DI wiring in `deps.py` based on `MOCK_AI`.
- `scripts/smoke_gemini.py`: with a real key, runs one text call, one image call (generate a simple test image or accept a path argument) and one function-call round trip, printing the model used and latency.
- **Accept:** unit tests for the mock; a test that `GeminiClient` falls back to the fallback model when the primary raises (monkeypatch the SDK call); `smoke_gemini.py` runs when a key is present (skip otherwise).

### M5 — Food scan pipeline
- `scan_service.py` implementing flow A from `02_ARCHITECTURE.md`; routes `POST /scans`, `GET /scans`, `GET /scans/{id}`, `DELETE /scans/{id}`.
- Default `meal_type` from local time: 05–10 breakfast, 11–15 lunch, 19–22 dinner, else snack.
- Rate limit on `POST /scans`.
- **Accept:** tests: happy path returns `ScanResult` with ≥ 1 item, server-computed totals equal to the sum of items, health score in range, classifier predictions present; `NOT_FOOD` path stores a rejected scan and returns 422; other users' scan → 404; list pagination.

### M6 — Scan editing, tips and logging; intake
- `PATCH /scans/{id}/items` (grams rescale, rename/add via text estimate, remove), `POST /scans/{id}/tips`, `POST /scans/{id}/log`.
- `intake_service.py`: `POST /intake/describe`, `POST /intake`, `GET /intake/daily`, `GET /intake/summary`, `DELETE /intake/{id}`. `local_date` is computed from the profile timezone.
- **Accept:** gram edit rescales linearly and recomputes totals and score; logging twice → 409; daily totals equal the sum of the day's entries; summary returns `days` entries with zero-filled missing days; describe with `log=true` creates an entry.

### M7 — Insights
- `insight_service.py` + `GET /insights/daily` with cache on `(user, date, totals_hash)`.
- **Accept:** a second call with unchanged totals doesn't call the LLM (assert on the mock call count); `no_data` status with no entries.

### M8 — Chatbot
- `chat/context.py`, `chat/tools.py`, `chat/chat_service.py`; routes for sessions, messages (multipart, optional image), SSE stream and suggestions.
- **Accept:** tests: create session (with and without `scan_id`); send text → assistant reply saved; "how did I do today" triggers `get_daily_intake` (tool trace in `tool_calls`); "log 2 roti and dal for dinner" creates an intake entry with `source=chat`; image message stored with `image_url`; stream endpoint emits `user_message`, `delta`…, `done` in order; history limit respected; other users' sessions → 404; empty message → 400.

### M9 — Hardening
- Rate limits on all AI endpoints (`/scans` POST, `/scans/{id}/tips`, `/intake/describe`, `/insights/daily`, chat messages) → `RATE_LIMITED` envelope.
- Structured logs (request id, user id, route, latency, model used). Make sure no secrets or image bytes are logged.
- Consistent envelope for **all** errors, including 404 on unknown routes and 405.
- OpenAPI polish: tags, summaries, examples; export `docs/openapi.json` (script `scripts/export_openapi.py`).
- **Accept:** full test suite green; `ruff` clean; `openapi.json` exported.

### M10 — Delivery
- Dockerfile (python:3.11-slim, CPU torch wheel, non-root user, `HF_HOME` cache volume, healthcheck on `/api/v1/health`), `docker-compose.yml` (api + postgres 16, env from `.env`, runs `alembic upgrade head` on start).
- `scripts/seed_demo.py` (demo user `demo@nutriscan.app` / `demo12345`, a filled profile, 3 days of intake).
- `README.md` and `docs/FRONTEND_HANDOFF.md` per `07_TESTING_AND_DELIVERY.md`.
- `ml/finetune_indian_food.py` + `ml/README.md` (optional section §9 of the pipeline doc; must compile, not run).
- **Accept:** `docker compose up` works (if Docker is available; otherwise document the steps); README quick start verified locally with SQLite and `MOCK_AI=true`; final report written.
