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
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [API](#api)
- [How it works](#how-it-works)
- [Database](#database)
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
│   ├── core/               Settings, errors, logging, security, rate limiting, signed media URLs
│   ├── data/               Curated foods table (IFCT 2017 / USDA, per 100 g)
│   ├── db/                 Engine, session and ORM models
│   ├── schemas/            Request and response models
│   ├── services/           Business logic: scan pipeline, nutrition, health engine, chat, insights
│   │   └── llm/            Gemini client, mock client, prompts, output schemas, retry policy
│   └── main.py             App factory and start-up
├── alembic/                Database migrations
├── certs/                  Supabase root CA (TLS verification for the managed Postgres pooler)
├── docker/                 Container entrypoint (runs migrations, then the server)
├── docs/                   openapi.json and example payloads for every endpoint
├── frontend/               Web app served at /app/
├── ml/                     Optional fine-tuning script for Indian dishes
├── scripts/                Seeding, smoke test, OpenAPI export, example generation, guest cleanup
├── tests/                  pytest suite (tests/live holds opt-in calls to the real Gemini API)
├── Dockerfile
├── docker-compose.yml      API + PostgreSQL 16
├── pyproject.toml          ruff and pytest configuration
└── requirements*.txt       Runtime and development dependencies
```

## Getting started

### Local (SQLite)

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only PyTorch
pip install -r requirements-dev.txt
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
cp .env.example .env          # set GEMINI_API_KEY, JWT_SECRET (and MOCK_AI=false)
docker compose up --build     # API on :8000 + PostgreSQL 16; runs `alembic upgrade head` on start
docker compose exec api python scripts/seed_demo.py   # optional demo data
```

The image is `python:3.11-slim` with CPU-only PyTorch, runs as a non-root user, keeps uploads and the model
cache in the `appdata` volume (`/data`), and has a health check on `/api/v1/health` (180 s start period for the
first model download).

## Configuration

All settings come from environment variables (or `.env`); see [`.env.example`](.env.example).

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod`. Dev and test create tables automatically; prod relies on Alembic and requires a real `JWT_SECRET` |
| `LOG_LEVEL` | `INFO` | JSON-lines logs with a request id |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Used to build absolute image URLs |
| `CORS_ORIGINS` | `*` | Comma-separated allowed origins |
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
| `CHAT_HISTORY_TURNS` | `20` | Messages sent to Gemini per request |
| `CHAT_MAX_TOOL_ROUNDS` | `4` | |
| `FRONTEND_DIR` | `./frontend` | Web app served at `/app/` |

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
| System | `GET /health` · `GET /meta` | Status of database, classifier and Gemini · units, labels, enums, thresholds |
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

- Interactive reference: `/docs` and `/redoc`. The exported schema is [`docs/openapi.json`](docs/openapi.json)
  (`python scripts/export_openapi.py`).
- Real example payloads for every endpoint are in [`docs/examples/`](docs/examples)
  (`python scripts/generate_examples.py`, runs in mock mode).

## How it works

### Scan pipeline (`POST /api/v1/scans`)

```
upload ─► validate and normalise (type check, EXIF orientation, strip metadata, ≤1024 px, JPEG, sha256)
       ─► save to storage
       ─► classifier top-k dish hints                  [threadpool; skipped if disabled or failing]
       ─► Gemini vision: items with grams, nutrients, confidence, plus 2–3 tips (one structured-JSON call)
             └─ not food ─► scan stored as rejected ─► 422 NOT_FOOD
       ─► nutrients from the curated foods table where the dish is known, else the model's estimate
       ─► sanitise (clamps, Atwater check) ─► plate totals = Σ items
       ─► health score and flags against the user's targets
       ─► persist and return
```

The classifier is the transfer-learning component: a ViT pretrained on ImageNet-21k and fine-tuned on
Food-101. Food-101 is single-label and Western-heavy, so its predictions are only hints; Gemini makes the
multi-item decision.

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
save user message (+ photo) ─► system prompt from profile, targets, today's intake, linked scan
 ─► recent messages (only the current one carries image bytes)
 ─► Gemini with tools ─► function calls? ─► run tools scoped to this user (get_daily_intake, log_meal, …)
 ─► save reply and tool trace ─► JSON, or SSE: user_message → tool* → delta* → done
```

Tool rounds are capped by `CHAT_MAX_TOOL_ROUNDS`. Replies respect diet type and allergies, avoid diagnoses,
and respond supportively to signs of disordered eating.

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
(HMAC over the path, valid for `MEDIA_URL_TTL_S`). Guest accounts are deleted with their photos after
`GUEST_RETENTION_DAYS`, on start-up and via `python scripts/cleanup_guests.py` (schedule it daily in
production).

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
- No refresh tokens, email verification or password reset; tokens cannot be revoked before they expire.
