# 01 — Project Brief

## Problem statement (verbatim intent)
> Students staying in hostels or living independently often consume unhealthy food without understanding its nutritional impact. Develop an AI-powered nutrition scanner that analyzes food images and provides estimated nutritional information.
>
> **Data considerations:** The application may use food image datasets and nutrition-related information such as calorie values and nutrient estimates. Teams should consider handling images containing multiple food items while providing approximate but meaningful nutritional insights.
>
> **Solution expectations:** The solution should allow users to upload food images and receive information about estimated calories, nutrition values, or health suggestions. The interface should encourage healthy eating awareness and present information in a simple and visually appealing manner.

## Reference project
Design is adapted from **ScanMyFood** (https://github.com/nikhileshmeher0204/ScanMyFood), which is a Flutter + Spring Boot app calling Gemini via Vertex AI. We reuse its **ideas**, not its code:
- Its per-item food analysis prompt (canonical names, portion cues, Indian localisation, Atwater factors), adapted in `05_AI_PIPELINE.md`.
- Its response shape (meal name → analysed items → plate totals).
- Its plate aggregation logic (sum per-item nutrients server-side).
- Its onboarding data (health metrics, preferences, conditions, country) for personalisation.
- Its chat-with-tools concept (get daily intake, log meal via description).

What we add that the reference lacks: a **transfer-learned classifier** in the pipeline, a **deterministic health score**, a **persisted multimodal chatbot**, and a **frontend-ready API with mock mode**.

## Requirements
### Functional
| ID | Requirement | Covered by |
|---|---|---|
| FR1 | Upload a food image (jpeg/png/webp, ≤ 8 MB) | `POST /scans` |
| FR2 | Recognise food with an AI model trained via transfer learning | Classifier service (ViT fine-tuned on Food-101) |
| FR3 | Handle **multiple food items** in one image | Gemini vision per-item breakdown |
| FR4 | Estimated calories + nutrients per item and per plate | Gemini estimates + server-side totals |
| FR5 | Approximate but meaningful: confidence per item, editable items and portions | `confidence` field, `PATCH /scans/{id}/items` |
| FR6 | Health suggestions that encourage healthy eating | Health engine (score, flags) + Gemini tips |
| FR7 | Output simple for a visual UI | Score 0–100, colour label, flags, fixed nutrient keys |
| FR8 | Personalised to the user (targets from profile, diet type, allergies) | Profile + targets + prompt context |
| FR9 | Track daily intake and trends | Intake endpoints |
| FR10 | **Chatbot** for food and nutrition questions, text and image input, aware of user context | Chat endpoints + Gemini function calling |
| FR11 | Log meals from a text description ("2 roti and dal") | `POST /intake/describe`, chatbot tool |
| FR12 | Reject non-food images gracefully | `is_food` check → `NOT_FOOD` error |

### Non-functional
- Scan latency target: **p95 < 6 s** (classifier < 1 s on CPU; Gemini is the bulk).
- Works with no GPU. Classifier runs on CPU.
- Runs locally with **SQLite and one command**; production-ready for PostgreSQL + Docker.
- **Mock mode** (`MOCK_AI=true`) for tests and frontend development.
- Security: JWT auth, bcrypt passwords, upload validation, size limits, basic rate limiting on AI endpoints, CORS configurable.
- Observability: structured logs with request id, per-scan latency, and the model versions used.

## Scope
**In scope:** auth, user profile and targets, food scanning, scan editing, intake logging, daily and weekly summaries, daily insights, chatbot (sessions, text + image, tools, SSE streaming), meta endpoints, mock mode, tests, Docker, README, OpenAPI.

**Optional (only after everything else passes):** an offline fine-tuning script for Indian food (`ml/`), which is **not run** during the build.

**Non-goals:** frontend, barcode/label scanning, payments, push notifications, admin panel, image generation, OAuth or social login.
