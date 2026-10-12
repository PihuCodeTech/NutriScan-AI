# How to use this kit

1. Put this whole folder (`CLAUDE.md`, `.env.example`, `docs/`, this file) in an **empty project folder**, e.g. `nutriscan-backend/`.
2. Copy `.env.example` to `.env` and paste your Gemini API key (from https://aistudio.google.com/apikey). No key? Leave it blank and Claude Code will build and test everything in mock mode.
3. Make sure Python 3.11+ is installed. Docker is optional.
4. Open a terminal in the folder and run `claude`.
5. Paste the prompt below. Accept the permission prompts, or run in auto-accept mode so it can work through all milestones without stopping.

---

## Prompt (copy everything between the lines)

---
You are building the complete backend for "NutriScan AI", an AI food nutrition scanner with a Gemini-powered nutrition chatbot, for students living in hostels. The frontend will be built separately later, so the API contract matters as much as the features.

Before writing any code:
1. Read `CLAUDE.md` fully, then read every file in `docs/` in numeric order (01 → 07). These are the source of truth. The precedence rules are in `CLAUDE.md`.
2. Create a task list that mirrors the milestones M0–M10 in `docs/06_BUILD_PLAN.md`.

Then build the whole backend in one go, milestone by milestone:
- Follow the folder layout, API spec, data model, prompts, formulas and conventions exactly as documented. Where the docs leave a detail open, choose the simplest robust option and record it in `DECISIONS.md`.
- After every milestone, run `ruff check .` and `pytest -q`. Fix all failures before starting the next milestone. Tests must never call the network (use `MOCK_AI=true` and the mock clients).
- Set up a Python virtual environment in `.venv` and install dependencies there. Install CPU-only PyTorch.
- All Gemini access goes through `app/services/llm/gemini_client.py` using the official `google-genai` SDK, with model names from env vars. If the installed SDK's API differs from the reference snippets in `docs/05_AI_PIPELINE.md`, check the official docs (https://ai.google.dev/gemini-api/docs) and adapt inside that file only.
- If `.env` contains a `GEMINI_API_KEY`, run `scripts/smoke_gemini.py` after milestone M4 and again at the end, and fix any integration issues. If there is no key, complete everything in mock mode and say so clearly in the report.
- Don't stop to ask me questions unless you're truly blocked (for example a dependency can't be installed). Make a reasonable decision, note it in `DECISIONS.md`, and continue.
- Don't skip milestones or leave TODO stubs in required features. `ml/finetune_indian_food.py` must be written but not executed.

When everything is done:
- Start the server once (`uvicorn app.main:app`) and hit `/api/v1/health` to confirm it boots. Export `docs/openapi.json`.
- Write `README.md`, `docs/FRONTEND_HANDOFF.md` and `BUILD_REPORT.md` as described in `docs/07_TESTING_AND_DELIVERY.md`.
- Finish with a short summary: what was built, test results, whether the real Gemini smoke test passed, the commands to run it, and any deviations.
---

## If the session stops partway
Start Claude Code again in the same folder and paste:

> Continue building NutriScan AI. Re-read `CLAUDE.md` and `docs/06_BUILD_PLAN.md`, check which milestones are already complete (run `pytest -q` and inspect the code), then continue from the first incomplete milestone using the same rules as before.
