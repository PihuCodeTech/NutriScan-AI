# 07 — Testing, Delivery and Frontend Handoff

## Testing strategy
- `tests/conftest.py`: sets `APP_ENV=test`, `MOCK_AI=true`, a temp `STORAGE_DIR`, and a fresh SQLite DB per test session (file in tmp dir or `sqlite+aiosqlite:///:memory:` with a shared connection). Provides `client` (httpx `AsyncClient` with `ASGITransport`), `auth_headers` (registers and logs in a user), `second_user_headers`, and `sample_jpeg` (a generated 256×256 Pillow image with some colour blobs).
- **No test may hit the network** (no Gemini, no Hugging Face). The real `GeminiClient` is tested by monkeypatching the SDK call.
- Test files: `test_health_meta.py`, `test_auth_users.py`, `test_health_engine.py`, `test_nutrition.py`, `test_images.py`, `test_llm_client.py`, `test_scans.py`, `test_scan_edit_log.py`, `test_intake.py`, `test_insights.py`, `test_chat.py`, `test_chat_stream.py`, `test_errors.py`.
- Target ≥ 80% line coverage on `app/services` (add `pytest-cov` and report it).
- Optional live test `tests/live/test_gemini_live.py`, marked `@pytest.mark.live` and skipped unless `GEMINI_API_KEY` is set and `RUN_LIVE=1`.

## Manual verification with a real key
1. `.env`: set `GEMINI_API_KEY`, `MOCK_AI=false`.
2. `python scripts/smoke_gemini.py` → prints model, latency and OK for text, image and tool calls.
3. `uvicorn app.main:app --reload` → `/docs` → register → Authorize → `POST /scans` with a real thali photo → check items, totals, score and tips.
4. Chat: create a session with that `scan_id` → ask "Is this enough protein for me?" → then "log it as lunch" → `GET /intake/daily` shows it.

## README.md must contain
- What the project is (2 paragraphs, including where transfer learning is used).
- Architecture diagram (ASCII or mermaid) and the scan and chat flows.
- Quick start: Python venv, `pip install`, copy `.env.example` → `.env`, get a Gemini key from Google AI Studio (https://aistudio.google.com/apikey), `alembic upgrade head`, `uvicorn`. First run downloads the ~350 MB classifier.
- Mock mode for frontend developers (`MOCK_AI=true`, no key, no download).
- Docker quick start.
- Environment variable table.
- Endpoint overview table (link to `/docs` and `docs/openapi.json`).
- Testing commands.
- How to switch to a self-fine-tuned model (`CLASSIFIER_MODEL_ID`, see `ml/README.md`).
- Limitations: estimates are approximate; Food-101 has limited Indian coverage (hence Gemini refinement); not medical advice.

## `docs/FRONTEND_HANDOFF.md` must contain
- Base URL, auth flow (register/login → Bearer token, 7-day expiry, 401 → re-login).
- The envelope and error-code table, and how to show errors.
- For each screen the likely calls, in order:
  - Onboarding: `PUT /users/me/profile` → `GET /users/me/targets`.
  - Scan: `POST /scans` (multipart) → render items, totals, `health.color`/`score`, flags as chips, tips; edit portions via `PATCH /scans/{id}/items`; "Add to today" → `POST /scans/{id}/log`.
  - Home/dashboard: `GET /intake/daily`, `GET /insights/daily`, `GET /intake/summary?days=7`.
  - Chat: `GET /chat/suggestions` → `POST /chat/sessions` (pass `scan_id` from the scan screen's "Ask AI about this meal") → `POST .../messages/stream` (SSE via `fetch` + ReadableStream, because `EventSource` can't POST multipart) or the non-streaming endpoint.
- `GET /meta` for units, labels and colours, so nothing is hard-coded in the UI.
- Image URLs are absolute (`PUBLIC_BASE_URL`).
- Full example JSON for `ScanResult`, `IntakeEntry`, daily intake, insight, `ChatMessage` and the SSE sequence (generated from mock mode).
- How to run the backend in mock mode locally.

## Final report (print at the end of the build and save as `BUILD_REPORT.md`)
- Milestones completed and anything skipped or deviated from (with reasons, also in `DECISIONS.md`).
- Test results (count, pass/fail, coverage for `app/services`).
- Whether the real Gemini smoke test ran (and which model answered) or only mock mode was verified.
- Exact commands to run the project locally and in Docker.
- Known limitations and suggested next steps (Indian-food fine-tune, S3 storage, refresh tokens, etc.).
