# Decisions

Choices made where the docs left a detail open, or where the build deviated from them. Newest context first
within each section.

## Environment and setup
1. **No Gemini key was available.** The kit folder had no `.env` (only `.env.example`), so there was no
   `GEMINI_API_KEY` to verify. Everything was built and verified with `MOCK_AI=true`. A local `.env` was
   created from `.env.example` with `MOCK_AI=true` and a random `JWT_SECRET` (it's git-ignored). The live smoke
   test (`scripts/smoke_gemini.py`) and `tests/live/` are ready but were skipped.
2. **Model names left at the documented defaults** (`gemini-3.8-flash`, fallback `gemini-3.5-flash-lite`) because
   they couldn't be checked without a key. `scripts/smoke_gemini.py` lists the available Flash models and
   suggests replacements if either name is not found.
3. **`GEMINI_USE_VERTEX` setting added** (`false` = Gemini Developer API / AI Studio key, `true` = Vertex AI express
   mode API key). Both modes are supported inside `gemini_client.py` only. The smoke script tries the
   configured mode first and, on 400/401/403, the other mode, then tells you which value to set.
4. **Python 3.11 venv.** The machine's default `python3` is 3.14; 3.11 was used to match the Docker image
   (`python:3.11-slim`) and the widest PyTorch wheel support. CPU PyTorch from the PyTorch CPU index.
5. **`sqlalchemy[asyncio]`** (pulls in `greenlet`) is required for the async engine; `requirements.txt` says so.
6. **No git repo** was initialised in the kit folder, so the per-milestone `git commit` step was skipped.
7. **Ruff line length 120** (the default 88 made the prompt/fixture-heavy modules hard to read).

## API contract details
8. **Scan list items** use nested partial objects to mirror the spec's dot notation:
   `{id, status, image_url, meal_name, meal_type, totals: {calories}, health: {score, label, color} | null, created_at}`.
9. **Rejected (non-food) scans** are stored with `status="rejected"`, zero totals, no items and `health: null`.
   The `422 NOT_FOOD` error carries `details: {scan_id, reason}`. Editing, tips or logging a rejected scan →
   `422 VALIDATION_ERROR`.
10. **`GET /intake/daily`** also returns `health_status` (`on_track|over|under|no_data`, same rules as insights).
    `status_flags` is a list of `{nutrient, level: "high"|"low", percent, message}` chips: limit nutrients over
    100 %, calories over 110 %, and — once the day is over (past date or ≥ 20:00 local) — low calories
    (< 85 %), protein (< 60 %) and fibre (< 50 %).
11. **`GET /intake/summary`**: `averages` are over days that have at least one entry (zeros if none); each day
    also has an `entries` count, and `days_logged` is returned. `streak_days_logged` counts consecutive logged
    days ending today — or ending yesterday if nothing is logged yet today, so a streak isn't "broken" at
    breakfast time. `top_foods` = top 5 item names (case-insensitive) in the window.
12. **`GET /users/me/targets`** returns the Nutrients keys flat plus `basis`, `explanation`, `bmr`, `tdee`,
    `goal_nutrients` and `limit_nutrients`.
13. **405** responses use code `METHOD_NOT_ALLOWED` (not in the catalogue, but same envelope).
14. **Timestamps**: naive datetimes sent by clients are treated as UTC; all output is ISO-8601 UTC with `Z`.
15. **Profile validation** beyond the spec: height 80–250 cm, weight 20–350 kg, ≤ 20 allergies/conditions of
    ≤ 60 chars each (de-duplicated), `country` is a 2-letter code, `timezone` must be a valid IANA name.
    Sending `null` clears a field (except `country`/`timezone`, which keep their defaults).
16. **Chat session titles**: sessions start as `"New chat"`; the first message sets the title to its first ~6
    words (`"Food photo"` for an image-only first message). An explicit title is never overwritten.
17. **`/media` is public** (no auth on static files); paths are unguessable UUIDs. For production, switch
    `LocalStorage` for S3 + signed URLs (the `Storage` protocol allows this).

## Scan pipeline and editing
18. **Scan edits don't change an already-logged intake entry** — intake entries are snapshots. Delete the entry
    and log again to update it.
19. **Rename / add item**: the backend asks Gemini for `"{grams} g {name}"`, takes the first item, then rescales
    it linearly to the requested grams (in case the model answered for a different weight). Adding without
    `quantity_g` uses Gemini's estimated grams. A name Gemini doesn't recognise as food → `422 NOT_FOOD`.
20. **LLM tips are capped at 3**; nutrients from Gemini always go through `sanitize()` (Atwater check etc.).
21. **If Gemini fails during a scan**, the stored image is deleted and nothing is saved (`503`/`502`).
22. **Uploads**: besides `image/jpeg|png|webp`, an empty or `application/octet-stream` content type is accepted
    *if* Pillow identifies the bytes as JPEG/PNG/WebP (some mobile clients and `curl -F` omit the type).
    `MPO` (multi-picture JPEG from phone cameras) is treated as JPEG. Transparent PNGs are flattened on white.
    Decompression bombs (> 50 MP) are rejected as `INVALID_IMAGE`.
23. **The classifier is loaded at startup** (awaited in `lifespan`, in a worker thread). The first run downloads
    ~350 MB; later starts load from the Hugging Face cache (~8 s measured). The mock classifier reports
    `loaded`.

## Gemini client
24. **Retry policy**: timeout / 429 / 5xx / transport errors → retry the primary once after 1.5 s → fallback
    model once → `503 AI_UNAVAILABLE`. A 404 (model not found) skips the same-model retry and goes straight to
    the fallback. 400/401/403 are treated as fatal (no fallback) → `503 AI_UNAVAILABLE`, with the reason logged.
25. **JSON repair**: invalid structured output is re-asked once on the same model with "Return ONLY valid JSON
    matching the schema"; a second failure → `502 AI_BAD_RESPONSE` (no fallback, since that's not an
    availability problem).
26. **Missing key with `MOCK_AI=false`** → AI endpoints return `503 AI_UNAVAILABLE` ("not configured"); non-AI
    endpoints keep working and `/health` reports `gemini: "missing"`.
27. **Function calling** replays Gemini's own `Content` objects inside a turn so thought signatures (required
    by newer models) are preserved; tool responses are sent as `{"result": ...}` or `{"error": ...}`.

## Chatbot
28. **Streaming deviates slightly from §7.4**: instead of running the tool loop non-streamed and then making a
    *second* streamed call for the final answer (which would pay for the answer twice), every round is
    streamed with tools declared. Text deltas are forwarded as they arrive; if the round ends in function
    calls, a `tool` event is emitted per call, the tools run, and the next round streams. After
    `CHAT_MAX_TOOL_ROUNDS` the final round runs with tools disabled. The event order is unchanged
    (`user_message → tool* → delta* → done | error`). To support this, `LLMClient.chat_stream` accepts an
    optional `tools` argument and yields `StreamChunk`s (text deltas, then the complete turn).
    Retries/fallback apply only before the first chunk has been sent.
29. **Assistant message content** is the concatenation of all text the model produced across rounds (e.g. a
    short "Let me check…" before a tool call plus the final answer) — exactly what the stream showed.
30. **The user message is saved before the AI call.** If Gemini fails, the user message stays (non-streaming
    returns `503`; streaming emits `error`) and no assistant message is saved.
31. **History** = last `CHAT_HISTORY_TURNS` messages *including* the current one.
32. **Tool arguments** are coerced defensively (e.g. `days: 7.0` → 7, clamped to documented ranges); unknown
    tools and bad arguments are returned to the model as `{"error": ...}` and traced with a "Couldn't run …"
    summary.
33. **SSE** is implemented with a plain `StreamingResponse` (`text/event-stream`), so `sse-starlette` isn't a
    dependency. Validation errors (empty message, bad image, unknown session, rate limit) are returned as
    normal JSON envelopes *before* the stream starts. The stream uses its own DB session.

## Insights, limits, logging
34. **`no_data` insights** return a static, encouraging payload without calling Gemini (and aren't cached).
35. **Insight cache key** hashes the day's totals **plus** `health_status`, because status can change with the
    clock (after 20:00 a low day becomes `under`) while totals don't. Tips are normalised to exactly 3.
36. **Rate limits** are per user (JWT subject; per IP if unauthenticated) and per route, read from
    `RATE_LIMIT_AI` on every request. Applied to `POST /scans`, `PATCH /scans/{id}/items` (it calls Gemini),
    `POST /scans/{id}/tips`, `POST /intake/describe`, `GET /insights/daily` and both chat message endpoints.
    Storage is in-memory (single process); use Redis (`storage_uri`) when running several workers.
37. **Logs** are JSON lines with `request_id` (also returned as `X-Request-ID`), `user_id`, route, status and
    latency; Gemini calls log model, latency and token counts. Image bytes, tokens and keys are never logged.
38. **bcrypt** only uses the first 72 bytes of a password; longer passwords are truncated explicitly.

## Files beyond the documented layout
39. `app/services/user_service.py` (accounts/profile/targets helpers), `app/utils/timeutil.py` (timezone
    helpers), `app/api/v1/docs.py` (OpenAPI error examples), `scripts/export_openapi.py`,
    `scripts/generate_examples.py` (mock-mode payloads in `docs/examples/`), `docker/entrypoint.sh`,
    `tests/test_classifier.py`, `tests/test_migrations.py`.

## Fixes after the first live run (2026-10-11)
40. **AI errors say what went wrong.** `AI_UNAVAILABLE` now carries `details.reason`
    (`not_configured | auth | quota | model | timeout | network | bad_request | unavailable`) and a matching
    message, instead of always "temporarily unavailable". The stream `error` event includes `details` when set.
    The web app shows the message and a sidebar status "Connected · AI unavailable: <reason>".
41. **400 from Gemini is no longer always fatal.** A 400 about the API key (or 401/403) is still fatal (the
    fallback would reject the same key); any other 400 (e.g. a feature/schema one model doesn't support) now
    tries the fallback model.
42. **`.env` and relative paths resolve against the project folder** (not the current directory), so starting
    `uvicorn` from elsewhere no longer silently loses the key, creates a new empty database or drops `/app`.
    Pasted keys are trimmed of spaces/quotes. Shell variables that override `.env` are logged at startup.
43. **The classifier loads in the background** (`/health` → `classifier: "loading"`), so the API and web app are
    reachable during the first ~350 MB download; scans run without hints until it is loaded. This replaces
    decision 23's blocking load.
44. **Web app AI timeout raised to 120 s** (`frontend/config.js`), above the server's worst case
    (3 attempts × `GEMINI_TIMEOUT_S`=30 s + backoff ≈ 92 s), so the page no longer gives up first.
45. **Removed a hard-coded Gemini key** from the old prototype `files (1)/api.js` (it called the shut-down
    `gemini-2.0-flash` straight from the browser). That page now falls back to its sample data and points to
    `/app/`. The current app (`frontend/`) never sees the key.

## Everything AI goes through Gemini (2026-10-11, second pass)
46. **No sample results or canned answers in the web app.** The old local "guest mode" showed a built-in
    sample scan ("Samosa (2 pieces)") and rule-based chat replies without calling the server. "Continue as
    guest" now calls `POST /api/v1/auth/guest`, which creates a real throw-away account (`is_guest: true`),
    so guests get the same Gemini scans, chat, meal ideas and insight. Browsers that chose guest in the old
    version are moved to a guest session automatically. AI failures show the reason, never a fake answer.
47. **`POST /api/v1/recipes/suggest`** (new): Gemini meal ideas from the ingredients a student has, within
    their kitchen (`none|kettle|burner`), diet and allergies. Nutrients are sanitised server-side; recipes
    needing more equipment than allowed are dropped. Replaces the page's built-in recipe matcher.
48. **The daily insight is always written by Gemini**, including days with nothing logged (it was static
    text), and tips are no longer padded with canned ones.
49. **Faster Gemini calls.** `GEMINI_THINKING_LEVEL=low` (default) is sent to every call; a model that
    refuses the setting is retried without it and remembered. A timeout or 504 DEADLINE_EXCEEDED now goes
    straight to the fallback model instead of waiting another full timeout on the same slow model (the smoke
    test showed a 62 s text estimate: two 30 s timeouts on gemini-3.8-flash before the fallback answered).
50. **The server prints the web app address** at startup in dev: `NutriScan web app → <PUBLIC_BASE_URL>/app/`.
