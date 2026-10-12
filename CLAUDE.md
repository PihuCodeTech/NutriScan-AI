# CLAUDE.md — NutriScan AI Backend

This file is the persistent context for building this project. Read it fully, then read every file in `docs/` in numeric order before writing code.

## What we are building
A **backend-only** REST API for an **AI Food Nutrition Scanner** aimed at hostel / independent-living students (primarily in India). A separate team will build the frontend later, so the API contract, OpenAPI docs, and mock mode matter as much as the features.

Two AI features, both powered by the **Gemini API**:
1. **Food Scanner**: user uploads a food photo. A **transfer-learned image classifier** (ViT fine-tuned on Food-101) produces top-k dish hints, then **Gemini (vision)** identifies every item on the plate, estimates portions and nutrients, and the backend computes totals and a deterministic health score. Gemini also writes short tips.
2. **Nutrition Chatbot**: multi-turn chat about food, meals, and healthy eating. It accepts **text and optional images** (Gemini vision), knows the user's profile, today's intake and (optionally) a linked scan, and can call backend tools (function calling) to read intake data or log a meal.

## Source documents (read in order)
| File | Contents |
|---|---|
| `docs/01_PROJECT_BRIEF.md` | Problem statement, requirements, scope, non-goals |
| `docs/02_ARCHITECTURE.md` | Stack, folder layout, request flows, config |
| `docs/03_API_SPEC.md` | Every endpoint, request/response shapes, error codes |
| `docs/04_DATA_MODEL.md` | Database tables and relations |
| `docs/05_AI_PIPELINE.md` | Classifier, Gemini prompts and schemas, chatbot and tools, health engine formulas |
| `docs/06_BUILD_PLAN.md` | Ordered milestones with acceptance checks. **Follow this order.** |
| `docs/07_TESTING_AND_DELIVERY.md` | Tests, mock mode, Docker, README, frontend handoff |

If two documents disagree, the precedence is: `03_API_SPEC` > `05_AI_PIPELINE` > `04_DATA_MODEL` > the others.

## Non-negotiable conventions
- **Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 (async), Alembic.** Dev DB is SQLite (`aiosqlite`); prod is PostgreSQL (`asyncpg`), switched only by `DATABASE_URL`.
- **Gemini SDK:** use the official `google-genai` package (`from google import genai`). **All Gemini calls go through `app/services/llm/gemini_client.py` and nowhere else.** If the installed SDK's method names differ from what the docs here show, check https://ai.google.dev/gemini-api/docs and adapt *inside that one file only*.
- **Model names come from env vars** (`GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`), never hard-coded elsewhere. Defaults: `gemini-3.8-flash` and `gemini-3.5-flash-lite`.
- **Response envelope for every endpoint:** `{"success": bool, "code": str, "message": str, "data": ...}`. Errors use the same envelope with `success: false` and `data: null` (plus optional `details`).
- **JSON is snake_case.** All routes live under `/api/v1`.
- **Nutrients are always an object with these fixed keys** (units fixed, documented at `GET /api/v1/meta`):
  `calories` (kcal), `protein_g`, `carbohydrates_g`, `fat_g`, `saturated_fat_g`, `fiber_g`, `sugar_g`, `sodium_mg`.
- **The LLM never has the final say on numbers the backend can compute.** Plate totals, daily totals, targets and the health score are computed in Python. Gemini supplies per-item estimates and natural-language tips only.
- **Secrets only via `.env`.** Never commit keys. Keep `.env.example` up to date.
- **`MOCK_AI=true`** must make the whole API work with no Gemini key and no model download (fixtures), for tests and for the frontend team.
- CPU-bound work (classifier inference, image resizing) runs in a threadpool (`run_in_threadpool` / `anyio.to_thread`), never blocking the event loop.
- Type hints everywhere; `ruff` clean; small, focused modules; docstrings on public service functions.
- Every user-facing AI output carries `"disclaimer": "Estimates only — not medical advice."` where the spec says so.

## Safety and tone rules for AI outputs
- Friendly, practical, budget-aware tips (hostel mess, canteen, street food, instant noodles, cheap swaps like curd, dal, sprouts, eggs, fruit).
- No medical diagnosis or prescriptions. For medical conditions, give general guidance and suggest a doctor or dietitian.
- Never recommend crash diets, skipping meals, or intakes below a safe floor (see the health engine doc). If a user shows signs of disordered eating, respond supportively, avoid numbers and targets, and encourage talking to a professional or trusted person.
- Respect `diet_type` (veg / eggetarian / non_veg / vegan) and `allergies` in every suggestion.

## Working agreement for Claude Code
- Build milestone by milestone as in `docs/06_BUILD_PLAN.md`. After each milestone, run `ruff check .` and `pytest -q` and fix failures before moving on.
- Don't stop to ask questions unless truly blocked. Make a reasonable choice, note it in `DECISIONS.md`, and continue.
- If `GEMINI_API_KEY` is absent, build and test everything with `MOCK_AI=true`, and say so in the final report.
- At the end, produce the final report described in `docs/07_TESTING_AND_DELIVERY.md`.
