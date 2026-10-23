# NutriScan AI

NutriScan AI helps students in hostels and shared flats understand what they eat. Photograph a plate and it
identifies every item on it (a thali can have 6 to 8), estimates portions in grams, calories and eight
nutrients per item and per plate, and returns a health score from 0 to 100 with flags ("High in salt for one meal")
and practical, budget-friendly tips. A nutrition chatbot, NutriBuddy, answers food questions with text and
photos, knows the user's profile and today's intake, and can read their data or log a meal for them.

The project is a FastAPI backend (REST + SSE under `/api/v1`) with a web app served at `/app/`.

> *Estimates only — not medical advice.*

## Contents

- [Features](#features)
- [Principles and conventions](#principles-and-conventions)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API](#api)
- [How it works](#how-it-works)
- [Database](#database)
- [Monitoring](#monitoring)
- [Backups and recovery](#backups-and-recovery)
- [Fine-tuning the classifier](#fine-tuning-the-classifier)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)
- [Limitations](#limitations)

## Features

- Scan a photo of a meal or a nutrition label to get items, grams, nutrients, plate totals, a health score,
  flags and tips. Portions and items can be edited afterwards, and totals and score update instantly.
- Chat with NutriBuddy, with optional photos. It can read today's intake or log a meal through function
  calling, and replies stream over SSE.
- Track intake: daily totals against personal targets, N-day summaries, street-free streaks and
  home-cooked counts, and logging by description ("2 roti, dal and lassi").
- Get a short AI read of the day, and recipes from the ingredients a student actually has, respecting
  diet type, allergies and kitchen (none / kettle / burner).
- Try everything as a guest without signing up. Guest data is deleted after a few days.
- Run the whole API in mock mode, with no Gemini key and no model download, for tests and frontend work.

## Principles and conventions

**Who it's for.** Students in India living in hostels or on their own, eating at the mess, the canteen,
street stalls or from instant noodles: budget-conscious, on phones and laptops alike, with varied diets
(veg, eggetarian, non-veg, vegan) and allergies.

**Product principles**

1. The LLM never decides a number the backend can compute. Plate totals, daily totals, targets and the
   health score are computed in Python, and nutrients come from the foods table where possible. The UI
   marks table values ("DB") and AI estimates ("AI est.") so users know which is which.
2. A scan takes 10 to 40 s, so the user always sees progress, and a clear message if something fails.
3. Advice should be something a hostel student can act on today. Cheap, available swaps (curd, dal,
   sprouts, eggs, fruit) that respect `diet_type`, allergies and kitchen are preferred to ideal plans.
4. The tone encourages and never shames. No crash diets, skipped meals or intakes below a safe floor. No
   diagnoses or prescriptions; medical questions are referred to a doctor or dietitian. On signs of
   disordered eating, the app responds supportively, drops numbers and targets, and suggests talking to
   someone.
5. AI outputs carry *"Estimates only — not medical advice."* wherever the API spec says so.

**Code conventions**

- Python 3.11+, FastAPI, Pydantic v2, async SQLAlchemy 2.0, Alembic. Only `DATABASE_URL` switches SQLite
  and PostgreSQL.
- All Gemini calls go through `app/services/llm/gemini_client.py` (the only importer of `google.genai`).
  Model names come from `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL`, never hard-coded.
- Every endpoint returns the `{success, code, message, data}` envelope under `/api/v1`, in snake_case, with
  the fixed nutrient keys documented at `GET /api/v1/meta`.
- `MOCK_AI=true` must keep the whole API working without a key or model download.
- CPU-bound work (classifier, image resizing) runs in a thread pool, never on the event loop.
- Secrets only via `.env` (keep `.env.example` current). Type hints everywhere; `ruff check .` and
  `pytest -q` pass before a change is done.

**Non-goals:** barcode scanning, payments, push notifications, admin panel, social login. Don't invent
users, testimonials or accuracy figures: none exist yet.

## Tech stack

| Layer | Technology |
|---|---|
| API | Python 3.11+, FastAPI, Pydantic v2, Uvicorn |
| Database | SQLAlchemy 2.0 (async), Alembic; SQLite in development, PostgreSQL in production |
| AI | Gemini via `google-genai` (vision, structured JSON, function calling, streaming) |
| Image classifier | [`nateraw/food`](https://huggingface.co/nateraw/food): ViT-base fine-tuned on Food-101, CPU |
| Web app | Vanilla HTML, CSS and JavaScript (no build step) |
| Tooling | pytest, ruff, Docker |

## Project structure

```
.
├── app/                    FastAPI application
│   ├── api/v1/             Route handlers (auth, users, scans, intake, insights, chat, recipes, media, meta, health)
│   ├── core/               Settings, errors, logging, metrics, security, rate limiting, signed media URLs
│   ├── data/               Curated foods table (IFCT 2017 / USDA, per 100 g)
│   ├── db/                 Engine, session and ORM models
│   ├── schemas/            Request and response models
│   ├── services/           Business logic: scan pipeline, nutrition, health engine, chat, insights, monitoring
│   │   ├── chat/           Chat sessions, context building and function-calling tools
│   │   └── llm/            Gemini client, mock client, prompts, output schemas, retry policy
│   ├── utils/              Time-zone and meal-time helpers
│   └── main.py             App factory and start-up (background jobs, static web app)
├── alembic/                Database migrations
├── certs/                  Supabase root CA (TLS verification for the managed Postgres pooler)
├── docker/                 Container entrypoint (migrations, then the server); backup/ holds the backup scripts
├── docs/                   openapi.json and example payloads for every endpoint
├── frontend/               Web app served at /app/
├── ml/                     Optional fine-tuning script for Indian dishes
├── scripts/                Seeding, Gemini smoke test, OpenAPI export, example generation, guest cleanup, upload sweep
├── tests/                  pytest suite (tests/live holds opt-in calls to the real Gemini API)
├── Dockerfile
├── docker-compose.yml      API + PostgreSQL 16 + verified nightly backups
├── pyproject.toml          ruff and pytest configuration
└── requirements.txt        All dependencies (runtime and dev tools), pinned
```

## Getting started

### Local (SQLite)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only PyTorch
pip install -r requirements.txt
cp .env.example .env
```

Get a Gemini API key from [Google AI Studio](https://aistudio.google.com/apikey) and set it in `.env`:

```bash
GEMINI_API_KEY=your-key
GEMINI_USE_VERTEX=false      # true only for a Google Cloud Vertex AI key
MOCK_AI=false
JWT_SECRET=<a long random string>
```

Check the key, create the database and start the server:

```bash
python scripts/smoke_gemini.py      # text, image and function-call round trips; prints model and latency
alembic upgrade head
python scripts/seed_demo.py         # optional: demo@nutriscan.app / demo12345 with 3 days of meals
uvicorn app.main:app --reload
```

- Web app: http://localhost:8000/app/
- API docs: http://localhost:8000/docs (Swagger) and `/redoc`

The first start downloads the ~350 MB classifier into the Hugging Face cache (`HF_HOME`). It loads in the
background: the server answers straight away, `/api/v1/health` reports `classifier: "loading"`, and scans run
without classifier hints until it is `loaded`.

`.env` is always read from the project root, and relative paths in it resolve against that folder, so the
server can be started from any directory. A variable exported in the shell overrides `.env`; the server logs a
warning naming it at start-up.

### Mock mode

No key, no model download, deterministic responses:

```bash
cp .env.example .env    # then set MOCK_AI=true
uvicorn app.main:app --reload
```

Every endpoint works. Scans return a "Rajma Chawal Plate" fixture (3 items); a scan `description` containing
`not food` triggers `422 NOT_FOOD`; text estimates split on commas and "and"; chat messages containing "today"
call `get_daily_intake` and ones containing "log" call `log_meal`, so tool traces and SSE `tool` events can be
built against.

### Docker

```bash
cp .env.example .env          # set GEMINI_API_KEY, JWT_SECRET, POSTGRES_PASSWORD (and MOCK_AI=false)
docker compose up --build     # API on :8000 + PostgreSQL 16; runs `alembic upgrade head` on start
docker compose exec api python scripts/seed_demo.py   # optional demo data
```

The image is `python:3.11-slim` with CPU-only PyTorch, runs as a non-root user, keeps uploads and the model
cache in the `appdata` volume (`/data`), and has a health check on `/api/v1/health` (180 s start period for the
first model download).

### Production deployment

The image is the deployable unit: any container host (Cloud Run, Render, Fly.io, a VM with Docker) works.
On start the entrypoint runs `alembic upgrade head`, then `uvicorn` on port 8000.

**Required settings** (from the host's secret store, never committed):

| Variable | Production value |
|---|---|
| `APP_ENV` | `prod` (the image sets it). Refuses to start with a weak `JWT_SECRET` or `MOCK_AI=true` |
| `JWT_SECRET` | New random value of ≥ 32 characters, not the one used in development: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs everyone out |
| `DATABASE_URL` | PostgreSQL, e.g. the Supabase session pooler URI (see [Database](#database)) |
| `GEMINI_API_KEY` | A key for production use, ideally with a budget alert in Google Cloud |
| `PUBLIC_BASE_URL` | The public `https://` URL of the API (photo links are built from it) |
| `CORS_ORIGINS` | The frontend's origin(s), e.g. `https://app.example.com` (not `*`) |
| `FORWARDED_ALLOW_IPS` | The reverse proxy's address(es), so per-IP limits see real client IPs |

Startup logs a warning for each risky value it finds (`*` CORS, a non-https URL, no Gemini key, SQLite).

**Checklist**

1. **HTTPS:** terminate TLS at the platform or a reverse proxy (Caddy, nginx) in front of port 8000.
2. **One instance, one process:** rate limits and the insight cache are in memory. Don't add `--workers` or
   replicas.
3. **Persistent `/data` volume:** uploaded photos and the classifier cache (~350 MB, downloaded from
   Hugging Face on first start) live there. On a host without volumes, photos are lost on redeploy.
4. **Migrations:** run automatically on start and are additive. Back up the database before deploying a
   release that adds a migration.
5. **Health checks:** `GET /api/v1/health` is liveness (always 200, used by the container `HEALTHCHECK`);
   `GET /api/v1/health/ready` answers 503 when the database is unreachable. Point an uptime monitor at the
   second one.
6. **Monitoring and backups:** set `ALERT_WEBHOOK_URL`, add an external uptime check and confirm backups run
   (see [Monitoring](#monitoring) and [Backups and recovery](#backups-and-recovery)).

## Configuration

All settings come from environment variables (or `.env`); see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod`. Dev and test create tables automatically; prod relies on Alembic and requires a real `JWT_SECRET` |
| `LOG_LEVEL` | `INFO` | JSON-lines logs with a request id |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build absolute image URLs |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins. Set the frontend's origin(s) in prod (a warning is logged for `*`) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./nutriscan.db` | PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/db` (a plain `postgresql://` URL is converted) |
| `JWT_SECRET` | *(set it)* | HS256 signing key |
| `JWT_EXPIRE_MINUTES` | `10080` | 7 days |
| `GEMINI_API_KEY` | | From Google AI Studio (or a Vertex AI express key) |
| `GEMINI_USE_VERTEX` | `false` | `true` = Vertex AI express mode |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Primary model |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | Used on timeout, 429, 5xx or a missing primary model |
| `GEMINI_TIMEOUT_S` | `30` | Per call |
| `GEMINI_COOLDOWN_S` | `120` | How long an overloaded or failing model is tried last; `0` = off |
| `GEMINI_THINKING_LEVEL` | `low` | `minimal` / `low` / `medium` / `high`; empty = model default |
| `MOCK_AI` | `false` | `true` = mock Gemini and mock classifier |
| `CLASSIFIER_ENABLED` | `true` | `false` = scans skip classifier hints |
| `CLASSIFIER_MODEL_ID` | `nateraw/food` | Hugging Face id or a local path to a fine-tuned model |
| `CLASSIFIER_TOP_K` | `3` | |
| `MAX_UPLOAD_MB` | `8` | |
| `STORAGE_DIR` | `./storage/uploads` | Where uploaded photos are kept |
| `MEDIA_URL_TTL_S` | `86400` | Lifetime of a signed photo URL |
| `GUEST_RETENTION_DAYS` | `3` | Guest accounts older than this are deleted with their photos |
| `RATE_LIMIT_AI` | `20/minute` | Per user, per AI endpoint |
| `RATE_LIMIT_LOGIN` | `10/minute` | Per client IP |
| `RATE_LIMIT_REGISTER` | `20/hour` | Per client IP (guests: 30/hour per IP) |
| `CHAT_HISTORY_TURNS` | `20` | Messages sent to Gemini per request |
| `CHAT_MAX_TOOL_ROUNDS` | `4` | |
| `FRONTEND_DIR` | `./frontend` | Web app served at `/app/` |
| `METRICS_TOKEN` | | Bearer token for `GET /metrics`; empty = endpoint disabled |
| `ALERT_WEBHOOK_URL` | | Slack or Discord incoming webhook for alerts; empty = alerts are only logged |
| `ALERT_REPEAT_MIN` | `240` | Re-send a still-firing alert this often; `0` = once |
| `MONITOR_INTERVAL_S` | `60` | How often the watchdog checks the database and evaluates alert rules |
| `GUEST_CLEANUP_INTERVAL_H` | `24` | Guest cleanup runs on start-up, then this often (as does the unreferenced-photo sweep in prod) |

## API

All routes live under `/api/v1` and return the same envelope:

```json
{ "success": true, "code": "SCAN_CREATED", "message": "…", "data": { } }
```

Errors use the same shape with `success: false`, `data: null` and optional `details`. JSON is snake_case, and
nutrients always use the keys `calories`, `protein_g`, `carbohydrates_g`, `fat_g`, `saturated_fat_g`,
`fiber_g`, `sugar_g` and `sodium_mg` (units are listed by `GET /meta`).

| Area | Endpoints | Purpose |
|---|---|---|
| System | `GET /health` · `GET /health/ready` · `GET /meta` | Status of database, classifier and Gemini (`/ready` answers 503 when the database is down) · units, labels, enums, thresholds |
| Auth | `POST /auth/register` · `POST /auth/login` · `POST /auth/guest` | 7-day bearer token; guest = throw-away account |
| Users | `GET /users/me` · `PUT /users/me/profile` · `GET /users/me/targets` | Profile (partial update) and computed daily targets |
| Scans | `POST /scans` · `GET /scans` · `GET /scans/{id}` · `DELETE /scans/{id}` | Scan a photo, list, view, delete |
| | `PATCH /scans/{id}/items` · `POST /scans/{id}/tips` · `POST /scans/{id}/log` | Edit portions or items, regenerate tips, add to intake |
| Intake | `POST /intake/describe` · `POST /intake` · `GET /intake` · `GET /intake/daily` · `GET /intake/summary` · `DELETE /intake/{id}` | Text estimate, manual log, entries, daily view, N-day summary |
| Insights | `GET /insights/daily` | AI headline, summary and three tips over the day's numbers (cached) |
| Recipes | `POST /recipes/suggest` | Meal ideas from the user's ingredients, diet and kitchen |
| Chat | `POST /chat/sessions` · `GET /chat/sessions` · `GET/PATCH/DELETE /chat/sessions/{id}` | Sessions, optionally linked to a scan |
| | `POST /chat/sessions/{id}/messages` · `POST …/messages/stream` · `GET /chat/suggestions` | Text and photo messages, SSE streaming, starter prompts |
| Media | `GET /media/{path}?exp=&sig=` | Uploaded photos, only through signed, expiring URLs |

`GET /metrics` (Prometheus text) sits outside `/api/v1` and is disabled unless `METRICS_TOKEN` is set; see
[Monitoring](#monitoring).

- Interactive reference: `/docs` and `/redoc`. The exported schema is [`docs/openapi.json`](docs/openapi.json)
  (`python scripts/export_openapi.py`).
- Real example payloads for every endpoint are in [`docs/examples/`](docs/examples)
  (`python scripts/generate_examples.py`, runs in mock mode).

## How it works

### Overview

```
 browser: web app at /app/  (or any other client)
        │  HTTPS, bearer token, JSON envelope or SSE
        ▼
┌─────────────────────────── FastAPI process ───────────────────────────┐
│  /api/v1 routes ─► services (scan, intake, chat, insights, recipes)   │
│                      │            │              │                    │
│                      ▼            ▼              ▼                    │
│              health engine   ViT classifier   LLM client ──────────────┼──► Gemini API
│              (targets,       (thread pool)    gemini_client.py,       │
│               scores)                         or mock when MOCK_AI    │
│                                                                       │
│  background: watchdog and alerts, guest cleanup, upload sweep (prod), │
│              classifier load, DB keep-alive (PostgreSQL)              │
└───────────┬──────────────────────────────────────┬────────────────────┘
            ▼                                      ▼
   SQLite / PostgreSQL                      STORAGE_DIR (photos,
   (users, scans, intake, chat, foods)      served via signed URLs)
```

### Scan pipeline (`POST /api/v1/scans`)

```
upload
  │  content type and size check (MAX_UPLOAD_MB)            ─► 400 INVALID_IMAGE / 413 FILE_TOO_LARGE
  ▼
normalise   decode with Pillow, EXIF orientation, strip metadata, ≤ 1024 px, JPEG q85, sha256   [thread]
  ▼
save photo to STORAGE_DIR            (deleted again if any later step fails before the scan row is saved)
  ▼
classifier: top-k Food-101 dish hints             [thread; none if disabled, still loading or failing]
  ▼
Gemini vision, one structured-JSON call: items with grams, nutrients and confidence, plus 2–3 tips
  │
  ├─ not food ─► scan saved with status "rejected" ─► 422 NOT_FOOD (details carry the scan_id)
  ▼
per item: sanitise nutrients (clamp negatives, sub-nutrient ≤ parent, Atwater calorie check)
  ▼
per item: replace with foods-table values where the dish is known       nutrition_source = table | estimate
  ▼
plate totals = Σ items ─► health score and flags against the user's targets          (deterministic Python)
  ▼
save scan and items ─► 201 SCAN_CREATED
```

The classifier is the transfer-learning component: a ViT pretrained on ImageNet-21k and fine-tuned on
Food-101. Food-101 is single-label and Western-heavy, so its predictions are passed to Gemini as hints only,
and Gemini decides which items are on the plate.

The model never has the last word on numbers the backend can compute. Plate totals, daily totals, targets
and the health score are deterministic Python (`app/services/health_engine.py`). Each item reports
`nutrition_source: "table" | "estimate"`. Add foods by editing `app/data/foods_seed.json` and running
`python scripts/seed_foods.py`.

### Targets and health score

- Daily targets: Mifflin-St Jeor BMR × activity factor, −400 kcal to lose / +300 to gain, never below
  1,200 kcal or the BMR. Until a profile has age, sex, height, weight, activity and goal, a 2,000 kcal default
  is used and `GET /users/me/targets` reports `basis: "default"`.
- Meal score (0 to 100): each meal is compared with its share of the day (breakfast 25 %, lunch 35 %, dinner
  30 %, snack 10 %, or a neutral third when unknown). Points come off for sodium, sugar, saturated fat,
  calories and fat above that share, and for protein and fibre below it (halved for snacks). 75+ is good,
  50 to 74 moderate, below 50 needs attention.

### Chat (`POST /api/v1/chat/sessions/{id}/messages[/stream]`)

```
save user message (+ normalised photo)
  ▼
system prompt: profile, targets, today's intake, linked scan (if any)
  ▼
history: last CHAT_HISTORY_TURNS messages (only the current one carries image bytes)
  ▼
Gemini turn with tools ◄──────────────────────────────────────┐
  │                                                           │
  ├─ function calls ─► run each tool for this user only ──────┘  (at most CHAT_MAX_TOOL_ROUNDS rounds,
  │                                                               then one last turn without tools)
  ▼ text only
save assistant reply and tool trace
  ▼
JSON response, or SSE events: user_message, then tool / delta as they happen, then done (or error)
```

The tools are `get_user_profile`, `get_daily_intake`, `get_intake_summary`, `get_recent_scans`,
`get_scan_details`, `estimate_meal` and `log_meal` (`app/services/chat/tools.py`). Each one only sees the
current user's data. Replies respect diet type and allergies, avoid diagnoses, and respond supportively to
signs of disordered eating.

### Gemini reliability

All Gemini calls go through `app/services/llm/gemini_client.py`. Timeouts, 429s and 5xx responses fall back to
`GEMINI_FALLBACK_MODEL`; a model that is overloaded or failing is tried last for `GEMINI_COOLDOWN_S`; invalid
JSON is re-requested once. Model names come only from configuration.

### Web app

`frontend/` is plain HTML, CSS and JavaScript, served by the backend at `/app/` (load order: `config.js`,
`data.js`, `api.js`, `auth.js`, `app.js`). It renders from local data immediately and syncs with the server in
the background. Static asset URLs carry a `?v=N` query in `index.html`; bump it when changing CSS or JS.

### Photos and guests

Uploaded photos are not public. They are served only through `GET /api/v1/media/{path}` with a signed URL
(HMAC over the path with a key derived from `JWT_SECRET` for photo links only, valid for `MEDIA_URL_TTL_S`). Guest accounts are deleted with their photos after
`GUEST_RETENTION_DAYS`, on start-up and then every `GUEST_CLEANUP_INTERVAL_H` hours (or on demand with
`python scripts/cleanup_guests.py`). A photo whose scan or chat message fails to save is deleted
straight away. In production, photos that no row references and that are over a day old are swept on the same
schedule. Elsewhere, `python scripts/sweep_uploads.py` lists them and `--delete` removes them. Run it only
with the `DATABASE_URL` the photos belong to: against another database, every photo looks unreferenced.

## Database

SQLite is used locally; PostgreSQL (for example [Supabase](https://supabase.com) or [Neon](https://neon.tech))
in production. Only `DATABASE_URL` changes:

1. Copy the connection string. For Supabase, use the session pooler URI from *Project Settings → Database*.
2. Put it in `.env` as `DATABASE_URL`.
3. Run `alembic upgrade head`, then start the server. The foods table is seeded on first start.

TLS to Supabase is verified against `certs/supabase-ca.crt`. On PostgreSQL, start-up does not wait for the
database: table creation, seeding, guest cleanup and connection warm-up run in the background,
and a small pool of connections is kept alive so requests never pay for opening one. Choose a database region
close to your users: each round trip to a distant region adds hundreds of milliseconds.

## Monitoring

Monitoring is built into the app and needs no extra services or dependencies. It is sized for a single
instance, and the code is in `app/core/metrics.py` and `app/services/monitoring.py`.

| What | Where |
|---|---|
| Logs | JSON lines on stdout: one `request` line per call (method, route, status, latency, `request_id`, `user_id`), Gemini calls with tokens and latency, job runs and alerts. Successful health and metrics probes are not logged |
| Errors | Unhandled exceptions are logged with a traceback (`level=ERROR`) and counted; every error envelope is counted by `code` |
| Metrics | `GET /metrics` (Prometheus text, needs `Authorization: Bearer $METRICS_TOKEN`): requests and latency per route, slow non-AI requests, error codes, business events, Gemini calls, failures, tokens and latency, classifier failures, DB checks and pool use, background jobs, event-loop lag, memory, CPU, disk free |
| Uptime | `GET /api/v1/health/ready` for an external monitor (503 when the database is down) |
| Alerts | An in-process watchdog posts to `ALERT_WEBHOOK_URL` (and always logs `"msg": "alert firing"`) |

**Business events** are counted from each success envelope's `code`: `REGISTERED`, `GUEST_CREATED`,
`LOGGED_IN`, `SCAN_CREATED`, `INTAKE_LOGGED`, `MESSAGE_CREATED` / `MESSAGE_STREAMED`, `CHAT_CREATED`, and so
on. Failed logins appear as `app_errors_total{code="INVALID_CREDENTIALS"}`.

**Privacy.** Metric labels are route templates, codes and model names only: never ids, emails, raw paths or
message text. Logs carry a user's id but never their email, password, tokens or meal text. A redaction filter
also masks API keys, bearer tokens, JWTs, `password=`/`sig=` values and passwords in connection URLs, in
case an exception message contains one.

**Alert rules** (evaluated every minute; each one needs someone to act):

| Alert | Fires when | Usual fix |
|---|---|---|
| `database_down` | 3 database checks in a row fail (~3 min) | Database host, Supabase project paused, `DATABASE_URL` |
| `server_errors` | ≥ 5 HTTP 5xx and ≥ 5 % of requests in 5 min (Gemini's 502/503 excluded) | Search the logs for `level=ERROR` |
| `gemini_config` | Any AI request refused for auth, quota, model or a missing key | Key, billing or model name; run `scripts/smoke_gemini.py` |
| `gemini_unavailable` | ≥ 5 AI requests failed after retries and fallback, and ≥ 50 % of Gemini calls failed, in 5 min | Usually a Google outage; check the status page |
| `slow_requests` | ≥ 10 requests that made no Gemini call took > 3 s, and ≥ 10 % of requests, in 5 min | Database latency or pool exhaustion, event-loop lag; slow routes are in `nutriscan_http_slow_requests_total` and WARNING `request` log lines |
| `job_failed:<job>` | The last run of `guest_cleanup`, `upload_sweep` or `classifier_load` failed | Job logs (`"job": "<name>"`) |
| `job_overdue:<job>` | A scheduled job (`guest_cleanup`, `upload_sweep`) hasn't completed for 2 intervals and didn't fail: it hangs | Job logs; restart the API |
| `task_crashed` | A background task (watchdog, cleanup loop, keep-alive) died with an exception | Traceback in `background task crashed`; restart the API |
| `disk_low` | Uploads volume < 10 % or < 1 GiB free | Grow the volume or prune |
| `memory_high` | Container memory > 90 % of its limit (cgroup v2) | Bigger instance |
| `event_loop_blocked` | The event loop stalled > 2 s in 3 checks in a row | CPU-bound code outside the thread pool |

An alert is sent when it starts, repeated every `ALERT_REPEAT_MIN` while it lasts, and followed by a
`RESOLVED` message. Single blips (one failed check, one 500) don't page anyone.

**Set up in production** (about 10 minutes):

1. Create a Slack or Discord incoming webhook and set `ALERT_WEBHOOK_URL`.
2. Add an external uptime check (UptimeRobot, Better Stack, Healthchecks, Uptime Kuma) on
   `https://<host>/api/v1/health/ready` every 1 to 5 minutes, alerting after 2 failures. The process can't
   report its own crash, a dead host or a broken TLS/DNS setup, so this check covers those.
3. Optional: set `METRICS_TOKEN` and scrape `/metrics` (Grafana Cloud's free tier, or Prometheus) for
   dashboards. Useful queries:
   `histogram_quantile(0.95, sum by (le, route) (rate(nutriscan_http_request_duration_seconds_bucket[5m])))`,
   `sum by (event) (increase(nutriscan_events_total[1d]))`,
   `sum by (model, kind) (increase(nutriscan_gemini_tokens_total[1d]))`.
4. Set a budget alert on the Gemini key in Google Cloud. Token counts are in the metrics, but spend is not.

## Backups and recovery

**Docker Compose (bundled PostgreSQL).** The `backup` service ([`docker/backup/`](docker/backup)) runs at
start-up and then every `BACKUP_INTERVAL_HOURS` (24). Each run:

1. Dumps the database with `pg_dump` (custom format) to `./backups/db-<UTC time>.dump`.
2. Verifies the dump by restoring it into a scratch database (`<db>_restore_check`), checking that every
   core table and the schema version are present, logging row counts, then dropping the scratch database.
   A dump that has never been restored is treated as broken.
3. Archives the uploaded photos to `./backups/uploads-<UTC time>.tar.gz` and checks that the archive reads
   back.
4. Deletes backups older than `BACKUP_RETENTION_DAYS` (14). Files are owner-only (`0600`) because they contain
   every user's data.
5. On success, pings `BACKUP_HEARTBEAT_URL`, a dead-man's switch such as a free healthchecks.io check with a
   26-hour period, so you also hear about it when backups stop running. On failure, posts to
   `ALERT_WEBHOOK_URL` and pings `<heartbeat>/fail`.

`docker ps` shows the backup container as `unhealthy` once the last good backup is more than a day (plus 2
hours) old. Run one by hand with `docker compose exec backup sh /backup/backup.sh`.

**Copy backups off the machine.** `./backups` sits on the same disk as the database, so it doesn't survive
losing the host. Sync it somewhere else, for example with `rclone sync ./backups remote:nutriscan-backups`
from the host's cron.

**Restore** (replaces all data; runs in one transaction, so a failed restore leaves the database unchanged):

```bash
docker compose stop api
docker compose run --rm -e CONFIRM=yes backup sh /backup/restore.sh /backups/db-<STAMP>.dump
docker compose run --rm -T api sh -c 'tar -xzf - -C /data' < backups/uploads-<STAMP>.tar.gz   # photos
docker compose start api          # applies any newer migrations on start
```

Practise a restore once on a spare machine and time it; that gives you your real recovery time.

**Supabase.** Backups are Supabase's job: daily backups (and optional point-in-time recovery) on paid plans,
restored from the dashboard. Check what your plan includes. The free plan has no backups you can rely on, so
run `pg_dump "$DATABASE_URL" -Fc -f nutriscan.dump` on a schedule as well. Photos live on the API's `/data`
volume either way, so back that up separately.

## Fine-tuning the classifier

`ml/finetune_indian_food.py` continues the transfer learning: it starts from `nateraw/food`, replaces the
101-class head with your Indian classes and fine-tunes in two phases. Run it on a GPU (Colab or Kaggle).

1. Put the dataset in ImageFolder layout, for example the Kaggle "Indian Food Images" dataset (80 classes):
   ```
   ml/data/indian_food/<class_name>/*.jpg
   ```
   ```bash
   kaggle datasets download -d iamsouravbanerjee/indian-food-images-dataset -p ml/data --unzip
   ```
2. Train:
   ```bash
   pip install -r requirements.txt torchvision datasets accelerate
   python ml/finetune_indian_food.py --data-dir ml/data/indian_food --food101-classes 20
   ```
   Phase 1 trains the new head with the encoder frozen; phase 2 unfreezes the last four encoder layers.
   `--food101-classes N` mixes in N Food-101 classes so the model keeps its Western coverage. Output goes to
   `ml/output/indian-food-vit/` (about 20 to 40 minutes on a T4).
3. Set `CLASSIFIER_MODEL_ID=ml/output/indian-food-vit` (or a Hugging Face Hub id) and restart.
   `/api/v1/health` shows `"classifier": "loaded"` and scans report the model id in `classifier.model`.

`ml/data/` and `ml/output/` are git-ignored.

## Testing

```bash
ruff check .
pytest -q                                # mock mode, a temporary SQLite database per test, no network
pytest -q --cov=app --cov-report=term    # coverage
RUN_LIVE=1 pytest -q -m live             # optional: real Gemini call (needs GEMINI_API_KEY)
python scripts/smoke_gemini.py           # live smoke test: text, image, function call
```

## Troubleshooting

When Gemini cannot answer, AI endpoints return `503 AI_UNAVAILABLE` with `details.reason`, and the web app
shows the message on the page and in the sidebar:

| `details.reason` | Meaning | Fix |
|---|---|---|
| `not_configured` | `GEMINI_API_KEY` is empty | Set the key in `.env` and restart |
| `auth` | The key was rejected (invalid, revoked or wrong mode) | Run `python scripts/smoke_gemini.py`; it tries both modes and reports the `GEMINI_USE_VERTEX` value to use |
| `quota` | Rate limit or free-tier quota reached (429) | Wait a minute, or check the key's limits in AI Studio |
| `model` | A configured model is not available for this key | `smoke_gemini.py` lists available models and suggests names |
| `network` | The server cannot reach Google | Check the connection, proxy, VPN or firewall |
| `timeout` | No answer within the timeout after retries | Try again, or raise `GEMINI_TIMEOUT_S` |
| `bad_request` | Both models rejected the request | Try another photo or message; check the server log |

The server log records the provider error for each attempt (`"msg": "gemini attempt failed"`), never the key.

## Limitations

- Estimates are approximate. Portion size from one photo is uncertain; each item carries a `confidence`,
  and users can correct grams or items.
- Food-101 has limited Indian coverage, which is why the classifier is only a hint (and why `ml/` exists).
- Nothing here is medical advice. No diagnoses or prescriptions; medical questions are referred to a doctor or
  registered dietitian.
- Rate limiting and the insight cache are in memory (single process), and uploads are stored on local disk.
- Metrics are in memory and reset on restart. There is no distributed tracing and no error-tracking service
  (such as Sentry); the logs carry tracebacks and request ids instead.
- No refresh tokens, email verification or password reset; tokens cannot be revoked before they expire.
