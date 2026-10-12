# NutriScan AI — Backend

NutriScan AI helps students in hostels and shared flats understand what they eat. Snap a photo of a plate
and the API identifies **every item** on it (a thali can have 6–8), estimates portions in grams, calories and
eight nutrients per item and per plate, and returns a simple **0–100 health score** with colour, flags
("High in salt for one meal") and practical, budget-friendly tips (curd, dal, sprouts, eggs, fruit). A
**nutrition chatbot** ("NutriBuddy") answers food questions with text and photos, knows the user's profile
and today's intake, and can read their data or log a meal ("log 2 roti and dal for dinner").

**Where transfer learning is used:** every scan first goes through an image classifier,
[`nateraw/food`](https://huggingface.co/nateraw/food) — a ViT-base model pretrained on ImageNet-21k and
**fine-tuned on Food-101** (101 dishes, ~89 % accuracy), running on CPU. Its top-k predictions are passed to
**Gemini vision** as weak hints and returned to the UI ("model guess vs final analysis"). Because Food-101 is
single-label and Western-heavy, Gemini makes the final multi-item decision. `ml/finetune_indian_food.py` shows
the next transfer-learning step: fine-tuning that model on Indian dishes. The **LLM never has the last word on
numbers the backend can compute**: plate totals, daily totals, targets and the health score are all
deterministic Python.

> Backend only — a separate team builds the frontend. See [`docs/FRONTEND_HANDOFF.md`](docs/FRONTEND_HANDOFF.md).
> *Estimates only — not medical advice.*

---

## Architecture

```mermaid
flowchart LR
    FE[Frontend app] -->|REST + SSE, JWT| API[FastAPI /api/v1]
    API --> SVC[Services: scan, intake, insights, chat]
    SVC --> CLF[Food classifier<br/>ViT fine-tuned on Food-101<br/>CPU, threadpool]
    SVC --> LLM[gemini_client.py<br/>retry → fallback model<br/>JSON validation]
    LLM --> GEM[(Gemini API<br/>Developer or Vertex)]
    SVC --> HE[Health engine<br/>targets · score · flags<br/>deterministic]
    SVC --> DB[(SQLite dev /<br/>PostgreSQL prod)]
    SVC --> ST[(Local storage<br/>/media)]
    API -. MOCK_AI=true .-> MOCK[Mock Gemini + mock classifier<br/>fixtures, no network]
```

### Scan flow — `POST /api/v1/scans`
```
upload ─► validate & normalise (Pillow: type check, EXIF-orient, strip metadata, ≤1024 px, JPEG q85, sha256)
       ─► save to storage
       ─► classifier.predict(top-k)                      [threadpool; skipped if disabled/failed → classifier: null]
       ─► Gemini vision: items[] with grams, nutrients, confidence + 2–3 tips   (one structured-JSON call)
             └─ is_food = false ─► scan saved as "rejected" ─► 422 NOT_FOOD
       ─► sanitise nutrients (clamps, Atwater check) ─► per-100 g values
       ─► plate totals = Σ items                        [Python]
       ─► health score + flags vs the user's targets    [Python]
       ─► persist Scan + ScanItems ─► ScanResult
```
Editing portions (`PATCH /scans/{id}/items`) rescales linearly and recomputes totals/score instantly; renamed
or added items are re-estimated with a Gemini text call.

### Chat flow — `POST /api/v1/chat/sessions/{id}/messages[/stream]`
```
save user message (+ photo) ─► system prompt from profile, targets, today's intake, linked scan
 ─► last N messages (only the current one carries image bytes)
 ─► Gemini with tools ──► function calls? ─► run tools scoped to this user (get_daily_intake, log_meal, …)
          ▲                                        │  (≤ CHAT_MAX_TOOL_ROUNDS, then answer without tools)
          └────────────── results ─────────────────┘
 ─► save assistant message + tool trace ─► JSON, or SSE: user_message → tool* → delta* → done
```

## Quick start (local, SQLite)

Requires **Python 3.11+**.

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU-only PyTorch
pip install -r requirements-dev.txt
cp .env.example .env
```

Get a Gemini API key from **Google AI Studio: https://aistudio.google.com/apikey** and put it in `.env`:

```bash
GEMINI_API_KEY=your-key
GEMINI_USE_VERTEX=false      # AI Studio keys ("AIza…" or "AQ.…"); true only for a Google Cloud Vertex AI key
MOCK_AI=false
JWT_SECRET=<a long random string>
```

Check the key and models, then create the database and start the API:

```bash
python scripts/smoke_gemini.py          # text, image and function-call round trips; prints model + latency
alembic upgrade head
python scripts/seed_demo.py             # optional: demo@nutriscan.app / demo12345 with 3 days of meals
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** → `POST /auth/register` → **Authorize** with the token → `POST /scans`
with a food photo. The **first start downloads the ~350 MB classifier** (cached afterwards in the Hugging Face
cache, `HF_HOME`). It loads in the background: the API and the web app (http://localhost:8000/app/) answer
straight away, `/api/v1/health` shows `classifier: "loading"`, and scans run without classifier hints until it
is `loaded`.

`.env` is always read from the project folder (next to `app/`), and relative paths in it (`./nutriscan.db`,
`./storage/uploads`, `./frontend`) resolve against that folder, so it doesn't matter which directory you start
`uvicorn` from. A variable exported in your shell (e.g. an old `export GEMINI_API_KEY=…`) still **overrides**
`.env`. The server logs a warning naming it at startup; run `unset GEMINI_API_KEY` to fix that.

## Mock mode (for frontend developers)

No key, no model download, deterministic responses:

```bash
cp .env.example .env
# in .env:  MOCK_AI=true
uvicorn app.main:app --reload
```

Every endpoint works. Scans return a "Rajma Chawal Plate" fixture (3 items); a scan `description` containing
`not food` triggers `422 NOT_FOOD`; text estimates split on commas/"and" ("2 roti, dal and lassi"); chat
messages containing "today" call `get_daily_intake`, and ones containing "log" call `log_meal`, so tool traces
and SSE `tool` events can be built against. Example payloads for every screen are in
[`docs/examples/`](docs/examples) (regenerate with `python scripts/generate_examples.py`).

## Docker

```bash
cp .env.example .env        # set GEMINI_API_KEY, JWT_SECRET (and MOCK_AI=false)
docker compose up --build   # api on :8000 + postgres 16; runs `alembic upgrade head` on start
```

The image is `python:3.11-slim` with CPU-only PyTorch, runs as a non-root user, keeps uploads and the model
cache in the `appdata` volume (`/data`), and has a healthcheck on `/api/v1/health` (180 s start period for the
first model download). Seed demo data with `docker compose exec api python scripts/seed_demo.py`.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `APP_ENV` | `dev` | `dev` / `test` / `prod`. In dev/test tables are auto-created; prod relies on Alembic and requires a real `JWT_SECRET` |
| `LOG_LEVEL` | `INFO` | JSON-lines logs with request id |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | used to build absolute `image_url`s |
| `CORS_ORIGINS` | `*` | comma-separated list of allowed origins |
| `DATABASE_URL` | `sqlite+aiosqlite:///./nutriscan.db` | Postgres: `postgresql+asyncpg://user:pass@host:5432/nutriscan` |
| `JWT_SECRET` | *(set it)* | HS256 signing key |
| `JWT_EXPIRE_MINUTES` | `10080` | 7 days |
| `GEMINI_API_KEY` | | from Google AI Studio (or a Vertex express key) |
| `GEMINI_USE_VERTEX` | `false` | `true` = Vertex AI express mode |
| `GEMINI_MODEL` | `gemini-3.8-flash` | primary model |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash-lite` | used after a retry on timeout/429/5xx, or if the primary isn't found |
| `GEMINI_TIMEOUT_S` | `30` | per call |
| `MOCK_AI` | `false` | `true` → mock Gemini + mock classifier |
| `CLASSIFIER_ENABLED` | `true` | `false` → scans skip classifier hints |
| `CLASSIFIER_MODEL_ID` | `nateraw/food` | HF model id or a local path to a fine-tuned model |
| `CLASSIFIER_TOP_K` | `3` | |
| `MAX_UPLOAD_MB` | `8` | |
| `STORAGE_DIR` | `./storage/uploads` | served read-only at `/media` |
| `RATE_LIMIT_AI` | `20/minute` | per user, per AI endpoint |
| `CHAT_HISTORY_TURNS` | `20` | messages sent to Gemini per request |
| `CHAT_MAX_TOOL_ROUNDS` | `4` | |

## Endpoints

Interactive docs: **`/docs`** (Swagger) and **`/redoc`**. The exported schema is
[`docs/openapi.json`](docs/openapi.json) (`python scripts/export_openapi.py`). All routes are under `/api/v1`
and return `{success, code, message, data}`.

| Area | Method & path | What it does |
|---|---|---|
| System | `GET /health` · `GET /meta` | status of db/classifier/gemini · units, labels, enums, thresholds |
| Auth | `POST /auth/register` · `POST /auth/login` | returns a 7-day bearer token |
| Users | `GET /users/me` · `PUT /users/me/profile` · `GET /users/me/targets` | profile (partial update) and computed daily targets |
| Scans | `POST /scans` · `GET /scans` · `GET /scans/{id}` · `DELETE /scans/{id}` | scan a photo, list (paginated, `?date=`), view, delete |
| | `PATCH /scans/{id}/items` · `POST /scans/{id}/tips` · `POST /scans/{id}/log` | edit portions/items, regenerate tips, add to intake |
| Intake | `POST /intake/describe` · `POST /intake` · `GET /intake/daily` · `GET /intake/summary` · `DELETE /intake/{id}` | text estimate (optionally log), manual log, daily view, N-day summary |
| Insights | `GET /insights/daily` | AI headline, summary and 3 tips over the day's numbers (cached) |
| Chat | `POST/GET /chat/sessions` · `GET/PATCH/DELETE /chat/sessions/{id}` | sessions (optionally linked to a scan) |
| | `POST /chat/sessions/{id}/messages` · `POST …/messages/stream` · `GET /chat/suggestions` | text + photo messages, SSE streaming, starter prompts |

## Testing

```bash
ruff check .
pytest -q                                   # MOCK_AI, temp SQLite per test, no network
pytest -q --cov=app --cov-report=term       # coverage (app/services ≈ 93 %)
RUN_LIVE=1 pytest -q -m live                # optional: real Gemini call (needs GEMINI_API_KEY in .env)
python scripts/smoke_gemini.py              # live smoke test: text, image, function call
```

## Using your own fine-tuned classifier

Train with `ml/finetune_indian_food.py` (see [`ml/README.md`](ml/README.md)), then set
`CLASSIFIER_MODEL_ID=ml/output/indian-food-vit` (or your Hugging Face Hub id) and restart. `/health` shows
`"classifier": "loaded"` and scan responses report the model id in `classifier.model`.

## Troubleshooting AI errors

When Gemini can't answer, AI endpoints return `503 AI_UNAVAILABLE` with a specific message and
`details.reason`. The web app shows the message on the page and in the sidebar ("AI unavailable: …"):

| `details.reason` | Meaning | Fix |
|---|---|---|
| `not_configured` | `GEMINI_API_KEY` is empty | Put your key in `.env`, restart |
| `auth` | Google rejected the key (invalid, revoked, wrong mode) | Check the key; run `python scripts/smoke_gemini.py`, which tries both modes and tells you the `GEMINI_USE_VERTEX` value to use |
| `quota` | Rate limit or free-tier quota reached (429) | Wait a minute, or check the key's limits in AI Studio |
| `model` | `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` not available for this key | `smoke_gemini.py` lists available models and suggests names |
| `network` | The server can't reach Google (offline, proxy, VPN, firewall) | Check the machine's internet connection |
| `timeout` | No answer within `GEMINI_TIMEOUT_S` × 3 attempts | Try again; raise `GEMINI_TIMEOUT_S` |
| `bad_request` | Both models rejected the request itself | Try another photo/message; check the server log |

The server log has the exact Google error for each attempt (`"msg": "gemini attempt failed"`), without the key.

## Limitations

- **Estimates are approximate.** Portion size from a single photo is inherently uncertain; each item carries a
  `confidence`, and users can correct grams or items.
- **Food-101 has limited Indian coverage** — the classifier often guesses Western dishes for Indian plates.
  That's why its output is only a hint and Gemini does the multi-item analysis (and why `ml/` exists).
- **Not medical advice.** No diagnoses or prescriptions; the chatbot is instructed to refer medical questions
  to a doctor or registered dietitian and to respond with care to signs of disordered eating.
- Rate limiting is in-memory (single process); uploads are on local disk and served publicly by unguessable
  URL. See `BUILD_REPORT.md` for next steps.

---

## Cloud database (Postgres)

User data is stored in SQLite locally and in **Postgres** in the cloud — no code change, just a setting. Free
options: [Neon](https://neon.tech) or [Supabase](https://supabase.com) (sign in with GitHub).

1. Create a free Postgres project and copy its connection string.
2. Change the prefix `postgresql://` → `postgresql+asyncpg://` and put it in `.env`:
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@host/dbname
   ```
3. Create the tables and seed the foods table, then start the server:
   ```
   alembic upgrade head        # creates every table on the fresh Postgres
   uvicorn app.main:app --reload
   ```
The server seeds the 52-food nutrition table on first startup and cleans up old guest accounts.

> Switching from the local `nutriscan.db` created before this version? Delete it first (`rm nutriscan.db`) so
> it's recreated with the current schema — it only holds demo/test data.

## How nutrition is estimated

Gemini identifies each item on the plate and estimates its weight in grams. The **server** then computes the
nutrients from a curated foods table (`app/data/foods_seed.json`, IFCT 2017 / USDA per-100 g values) wherever
the dish is known, and only falls back to the model's own numbers for foods not in the table. Each item in the
response carries `nutrition_source: "table" | "estimate"` so the UI (and judges) can see which is which. Add
more foods by editing the seed file and running `python scripts/seed_foods.py`.

## Photo privacy

Uploaded photos are **not** public. They are served only through `GET /api/v1/media/{path}` with a signed,
expiring URL (HMAC over the path, valid for `MEDIA_URL_TTL_S`, default 24 h). The URLs are generated for the
owner when scan/chat data is returned and work directly in `<img>` tags.

## Guest accounts

`POST /auth/guest` creates a throw-away account so people can try the AI without signing up. These are deleted
(with their photos) after `GUEST_RETENTION_DAYS` (default 3) on startup and via `python scripts/cleanup_guests.py`
(schedule it daily in production).

## The web app is a demo client

`frontend/` is a single-file vanilla-JS client for trying the backend end to end. It is intentionally not a
production frontend — that is a separate project. Treat `app.js` as a demo, not a template to extend.
