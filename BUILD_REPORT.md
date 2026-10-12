# Build report — NutriScan AI backend

Date: 2026-09-28 · Python 3.11 · FastAPI 0.141 · SQLAlchemy 2.1 · google-genai 2.25 · torch 2.14 (CPU) ·
transformers 5.17

## Headline

- **All milestones M0–M10 are implemented.** `ruff check .` is clean; `pytest -q` passes **131 tests, 1 skipped**
  (the opt-in live Gemini test). Coverage of `app/services` is **93 %** (target ≥ 80 %).
- **The real Gemini API was not called.** The kit folder had **no `.env` and no `GEMINI_API_KEY`**, so the key
  couldn't be checked in either Developer or Vertex mode. Everything was built and verified in
  **`MOCK_AI=true`**. The Gemini client (retry, fallback, JSON repair, function calling, streaming, and both
  auth modes) is unit-tested with the SDK monkeypatched. To finish the live check, add a key and run
  `python scripts/smoke_gemini.py` (see "What to do next").
- **The real transfer-learned classifier was verified**: `nateraw/food` downloads and loads on CPU (45 s the
  first time, ~8 s from cache), warm inference takes **~127 ms** (target < 1 s), and its predictions reach Gemini
  as hints in the real scan pipeline.

## Milestones

| | Milestone | Status | Notes |
|---|---|---|---|
| M0 | Scaffold, config, envelope, errors, logging, health/meta | ✅ | JSON logs with request id; `/docs` loads |
| M1 | DB models, Alembic (async), auth, profile | ✅ | Migration `0001` verified: upgrade → `alembic check` (no drift) → downgrade → upgrade; Postgres DDL checked offline |
| M2 | Nutrition + health engine, targets | ✅ | Hand-computed cases incl. 20 y/175 cm/70 kg/moderate/maintain → BMR 1698.75, 2630 kcal; floors; score boundaries |
| M3 | Images, storage, classifier | ✅ | Real HF model verified; mock classifier in tests (no downloads) |
| M4 | Gemini client + mock client + smoke script | ✅ code / ⚠️ live | Fallback, retry, 404→fallback, fatal auth, JSON re-ask, streaming all tested with fakes. Live smoke **skipped: no key** |
| M5 | Scan pipeline + routes, rate limit | ✅ | Rejected scans stored; images cleaned up if Gemini fails |
| M6 | Scan edit/tips/log; intake | ✅ | Linear gram rescale, rename/add via text estimate, 409 on double log, timezone-aware daily/summary |
| M7 | Insights with cache | ✅ | Cache hit asserted via mock call count; `no_data` needs no AI call |
| M8 | Chatbot: sessions, tools, multipart, SSE, suggestions | ✅ | 7 tools; tool loop limit; SSE order `user_message → tool* → delta* → done` |
| M9 | Hardening, OpenAPI | ✅ | Rate limits on all AI routes; envelope on 404/405/422/500; `docs/openapi.json` exported (23 paths) |
| M10 | Docker, seed, README, handoff, ml script | ✅ / ⚠️ Docker | Docker isn't installed on this machine, so `docker compose up` wasn't run; the files are written and the steps documented. README quick start verified locally with SQLite + mock mode. `ml/finetune_indian_food.py` passes `ruff` + `py_compile` and was **not** run, as instructed |

No git repository exists in the folder, so there are no per-milestone commits.

## Verification performed

- **Tests** (all with `MOCK_AI=true`, a fresh temp SQLite DB and storage dir per test, no network):

  | file | tests | | file | tests |
  |---|---|---|---|---|
  | test_health_meta | 5 | | test_scans | 12 |
  | test_auth_users | 9 | | test_scan_edit_log | 8 |
  | test_health_engine | 15 | | test_intake | 9 |
  | test_nutrition | 6 | | test_insights | 4 |
  | test_images | 12 | | test_chat | 13 |
  | test_classifier | 4 | | test_chat_stream | 5 |
  | test_llm_client | 21 | | test_errors | 7 |
  | test_migrations | 1 | | live/test_gemini_live | 1 (skipped) |

  Coverage: `app` 95 %, `app/services` 93 % (`pytest --cov=app`).
- **Real server, `MOCK_AI=false`, no key**: `uvicorn` boots, the real classifier loads, `/api/v1/health` →
  `{"status":"ok","db":"ok","classifier":"loaded","gemini":"missing"}`. `POST /scans` and chat messages return a
  clean `503 AI_UNAVAILABLE` envelope (no 500, no orphaned upload); non-AI endpoints (intake, daily) work; the
  bearer token never appears in logs.
- **Real classifier inside the scan pipeline** (mock Gemini): `201`, `classifier.model = "nateraw/food"`, top
  prediction passed to the LLM as a hint.
- **README quick start** (mock mode): `alembic upgrade head` → `seed_demo.py` (idempotent, run twice) →
  `uvicorn` → demo login → personalised targets (2530 kcal) → 3-day summary with streak 3 → scan `201`.

## Gemini

| | |
|---|---|
| Key present | **No** (no `.env` in the kit; created one from `.env.example` with `MOCK_AI=true`) |
| Modes supported | Developer API (`GEMINI_USE_VERTEX=false`) and Vertex AI express mode (`true`); smoke script auto-detects |
| Models configured | `gemini-3.8-flash` (primary), `gemini-3.5-flash-lite` (fallback) — **not verified** |
| Smoke test | `scripts/smoke_gemini.py` ran and **skipped** ("GEMINI_API_KEY is not set") |
| Live end-to-end scan/chat | **Not run** (needs a key) |

## How to run

**Local (SQLite):**
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements-dev.txt
cp .env.example .env          # add GEMINI_API_KEY (or set MOCK_AI=true), set JWT_SECRET
python scripts/smoke_gemini.py
alembic upgrade head
python scripts/seed_demo.py   # optional demo user: demo@nutriscan.app / demo12345
uvicorn app.main:app --reload # http://localhost:8000/docs
```

**Frontend developers (no key, no download):** set `MOCK_AI=true` in `.env`, then `uvicorn app.main:app --reload`.

**Docker (API + Postgres 16):**
```bash
cp .env.example .env          # set GEMINI_API_KEY, JWT_SECRET
docker compose up --build     # migrations run automatically; API on http://localhost:8000
```

**Checks:** `ruff check .` · `pytest -q` · `pytest -q --cov=app` · `python scripts/export_openapi.py`

## Deviations (details in `DECISIONS.md`)

- **Chat streaming** streams every tool-loop round (tools declared) instead of a non-streamed loop followed by a
  second streamed call, to avoid paying for the final answer twice. The SSE event contract is unchanged;
  `LLMClient.chat_stream` gained an optional `tools` argument and yields `StreamChunk`s.
- **Additive response fields**: `health_status` on `GET /intake/daily`; `entries` per day and `days_logged` on
  `GET /intake/summary`; `bmr`, `tdee`, `explanation`, `goal_nutrients`, `limit_nutrients` on targets; `status` on
  scan summaries. `status_flags` is defined as `[{nutrient, level, percent, message}]`.
- **Insights**: `no_data` days return a static nudge without an AI call; the cache key also includes
  `health_status`.
- `405` uses code `METHOD_NOT_ALLOWED` (not in the catalogue).
- Extra modules beyond the documented layout: `user_service.py`, `utils/timeutil.py`, `api/v1/docs.py`, and the
  scripts `export_openapi.py` / `generate_examples.py`.

## Known limitations

- Gemini behaviour with the real models is unverified (no key) — prompts and schemas follow the docs, and the
  client handles schema/JSON failures, but real-world portion accuracy hasn't been sampled.
- Food-101 rarely recognises Indian dishes (the test plate came back as "donuts"); it is used only as a hint.
- Rate limiting and the insight cache are per-process (in-memory limiter). Uploads are on local disk and
  `/media` is public by unguessable URL.
- No refresh tokens, email verification or password reset; JWTs can't be revoked before expiry.
- Editing a scan doesn't update an intake entry already logged from it (entries are snapshots).

## What to do next

1. **Add the key and run the live checks:** put `GEMINI_API_KEY=…` in `.env`, set `MOCK_AI=false`, run
   `python scripts/smoke_gemini.py`. It reports which mode works (and which `GEMINI_USE_VERTEX` to set) and,
   if a model name isn't found, lists the available Flash models and suggests replacements. Then run
   `RUN_LIVE=1 pytest -q -m live` and try a real thali photo at `/docs`.
2. Fine-tune the classifier on Indian dishes (`ml/README.md`) and set `CLASSIFIER_MODEL_ID`.
3. Production hardening: S3 (or similar) storage with signed URLs, Redis for rate limits, refresh tokens and
   password reset, and a background job queue if scan latency needs to be hidden from the UI.
4. Sample 30–50 real meals to calibrate the portion prompts and the health-score thresholds.
