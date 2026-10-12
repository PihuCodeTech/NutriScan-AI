# 03 — API Specification (v1)

Base path: `/api/v1`. All bodies are JSON unless marked *multipart*. All responses use the envelope:

```json
{ "success": true, "code": "SCAN_CREATED", "message": "Food analysed", "data": { } }
```
Errors:
```json
{ "success": false, "code": "NOT_FOOD", "message": "No food detected in the image.", "data": null, "details": null }
```
Auth: `Authorization: Bearer <jwt>` on every endpoint except `health`, `meta`, `auth/*`.
Timestamps are ISO-8601 UTC. IDs are UUID strings. Dates (`date` query params) are `YYYY-MM-DD` in the user's timezone (`profile.timezone`, default `Asia/Kolkata`).

---

## Shared objects

### `Nutrients`
```json
{ "calories": 0, "protein_g": 0, "carbohydrates_g": 0, "fat_g": 0,
  "saturated_fat_g": 0, "fiber_g": 0, "sugar_g": 0, "sodium_mg": 0 }
```
All numbers are floats rounded to 1 decimal place (calories and sodium to whole numbers).

### `FoodItem`
```json
{
  "id": "uuid",
  "name": "Roti",
  "canonical_name": "roti",
  "quantity_g": 80,
  "serving_description": "2 medium rotis",
  "confidence": "high",
  "source": "ai",
  "nutrients": { "...Nutrients" }
}
```
`confidence`: `high | medium | low`. `source`: `ai | user_edit | user_added`.

### `Health`
```json
{
  "score": 68,
  "label": "moderate",
  "color": "amber",
  "flags": [
    { "nutrient": "sodium_mg", "level": "high", "value": 1250, "meal_target": 700, "message": "High in salt for one meal" },
    { "nutrient": "protein_g", "level": "low",  "value": 9,    "meal_target": 20,  "message": "Low in protein" }
  ],
  "tips": ["Add a bowl of curd or an extra katori of dal for protein.", "Go easy on the pickle and papad to cut salt."],
  "disclaimer": "Estimates only — not medical advice."
}
```
`label`/`color`: `good/green` (≥75), `moderate/amber` (50–74), `needs_attention/red` (<50).

### `ScanResult`
```json
{
  "id": "uuid",
  "status": "completed",
  "image_url": "http://localhost:8000/media/2026/09/<file>.jpg",
  "meal_name": "Mess Lunch Thali",
  "meal_type": "lunch",
  "description": "hostel lunch",
  "classifier": {
    "model": "nateraw/food",
    "predictions": [ { "label": "chicken_curry", "display_name": "Chicken Curry", "score": 0.62 } ]
  },
  "items": [ "...FoodItem" ],
  "totals": { "...Nutrients" },
  "health": { "...Health" },
  "ai_model": "gemini-3.8-flash",
  "logged_intake_id": null,
  "created_at": "2026-09-28T09:30:00Z"
}
```
`status`: `completed | rejected` (`rejected` = not food). `classifier` may be `null`.

### Pagination
Query `?page=1&page_size=20` (max 100). Response `data`: `{ "items": [...], "page": 1, "page_size": 20, "total": 57 }`.

---

## System
| Method | Path | Description | Success code |
|---|---|---|---|
| GET | `/health` | `{status:"ok", db:"ok", classifier:"loaded|disabled|error", gemini:"configured|mock|missing", version}` | `OK` |
| GET | `/meta` | Nutrient keys with units and labels, meal types, diet types, activity levels, goals, health label thresholds, disclaimer text, max upload MB | `OK` |

## Auth
| Method | Path | Body | Returns | Code |
|---|---|---|---|---|
| POST | `/auth/register` | `{email, password (≥8), name}` | `{access_token, token_type:"bearer", user}` | `REGISTERED` (201) |
| POST | `/auth/login` | `{email, password}` | same | `LOGGED_IN` |

Errors: `EMAIL_TAKEN` (409), `INVALID_CREDENTIALS` (401), `UNAUTHORIZED` (401) for missing/expired tokens.

## Users
| Method | Path | Description | Code |
|---|---|---|---|
| GET | `/users/me` | `{id, email, name, profile, onboarding_complete}` | `OK` |
| PUT | `/users/me/profile` | Upsert profile (all fields optional; partial update) | `PROFILE_UPDATED` |
| GET | `/users/me/targets` | Computed daily targets (`Nutrients` shape + `basis` explaining how they were computed) | `OK` |

Profile fields: `age` (13–100), `sex` (`male|female|other`), `height_cm`, `weight_kg`, `activity_level` (`sedentary|light|moderate|active|very_active`), `goal` (`lose|maintain|gain`), `diet_type` (`veg|eggetarian|non_veg|vegan`), `allergies` (string[]), `conditions` (string[], free text such as "diabetes"), `country` (default `IN`), `timezone` (default `Asia/Kolkata`).
`onboarding_complete` = age, sex, height, weight, activity and goal are all set.

## Scans (food scanner)
| Method | Path | Body | Description | Code |
|---|---|---|---|---|
| POST | `/scans` | *multipart*: `image` (required), `description` (opt, ≤300 chars), `meal_type` (opt: `breakfast|lunch|dinner|snack`; default inferred from local time) | Full pipeline → `ScanResult` | `SCAN_CREATED` (201) |
| GET | `/scans` | pagination, `?date=` optional | List of `ScanResult` summaries (`id, image_url, meal_name, meal_type, totals.calories, health.score, health.label, created_at`) | `OK` |
| GET | `/scans/{id}` | | `ScanResult` | `OK` |
| PATCH | `/scans/{id}/items` | `{ "items": [ {"id": "...", "quantity_g": 120}, {"id": "...", "name": "Paneer Butter Masala"}, {"id": "...", "remove": true}, {"name": "Curd", "quantity_g": 100} ] }` | Edit: change grams (nutrients scaled linearly), rename (re-estimate that item with Gemini text), remove, or add new items (estimated with Gemini text). Recomputes totals and health (score/flags; tips kept). Returns `ScanResult` | `SCAN_UPDATED` |
| POST | `/scans/{id}/tips` | | Regenerate tips for the current items → `ScanResult` | `TIPS_UPDATED` |
| POST | `/scans/{id}/log` | `{ "meal_type": "lunch", "eaten_at": "..." }` (both optional) | Creates an intake entry from the scan; returns `IntakeEntry`. Logging twice → 409 `ALREADY_LOGGED` | `INTAKE_LOGGED` (201) |
| DELETE | `/scans/{id}` | | Deletes the scan and image file (not linked intake entries) | `DELETED` |

Scan errors: `INVALID_IMAGE` (400, unreadable or wrong type), `FILE_TOO_LARGE` (413), `NOT_FOOD` (422), `AI_UNAVAILABLE` (503), `RATE_LIMITED` (429), `NOT_FOUND` (404; also for other users' scans).

## Intake
`IntakeEntry`:
```json
{ "id": "uuid", "source": "scan|description|manual|chat", "scan_id": null, "name": "Mess Lunch Thali",
  "meal_type": "lunch", "eaten_at": "...", "items": [ "...FoodItem" ], "totals": { "...Nutrients" } }
```
| Method | Path | Body | Description | Code |
|---|---|---|---|---|
| POST | `/intake/describe` | `{ "text": "2 roti, dal and a glass of lassi", "meal_type": "dinner", "log": false }` | Gemini text estimate → `{items, totals, health}`; if `log=true` also saves and returns `intake_entry` | `DESCRIPTION_ANALYSED` |
| POST | `/intake` | `{ name, meal_type, eaten_at?, items: [{name, quantity_g, nutrients}] }` | Manual entry (frontend already has the numbers) | `INTAKE_LOGGED` (201) |
| GET | `/intake/daily` | `?date=` (default today) | `{ date, entries: IntakeEntry[], totals, targets, remaining, percent_of_target, status_flags }` | `OK` |
| GET | `/intake/summary` | `?days=7` (1–31) | `{ days: [{date, totals, calorie_percent}], averages, streak_days_logged, top_foods: [{name, count}] }` | `OK` |
| DELETE | `/intake/{id}` | | | `DELETED` |

## Insights
| Method | Path | Description | Code |
|---|---|---|---|
| GET | `/insights/daily` | `?date=`. `{ date, headline, summary, tips: string[3], health_status: "on_track|over|under|no_data", disclaimer }`. Gemini text over the day's totals vs targets. Cache per `(user, date, totals_hash)` | `OK` |

## Chat (nutrition chatbot)
`ChatMessage`:
```json
{ "id": "uuid", "role": "user|assistant", "content": "…markdown text…", "image_url": null,
  "tool_calls": [ { "name": "get_daily_intake", "args": {"date": "2026-09-28"}, "summary": "Fetched today's intake" } ],
  "created_at": "..." }
```
`tool_calls` appears on assistant messages only (a concise trace for the UI; raw tool payloads are stored but not returned).

| Method | Path | Body | Description | Code |
|---|---|---|---|---|
| POST | `/chat/sessions` | `{ "title"?: str, "scan_id"?: uuid }` | Create session; linking a scan puts that meal in the chatbot's context | `CHAT_CREATED` (201) |
| GET | `/chat/sessions` | pagination | `{id, title, scan_id, last_message_preview, updated_at}` | `OK` |
| GET | `/chat/sessions/{id}` | | `{session, messages: ChatMessage[]}` (oldest first) | `OK` |
| PATCH | `/chat/sessions/{id}` | `{ "title": str }` | Rename | `OK` |
| DELETE | `/chat/sessions/{id}` | | | `DELETED` |
| POST | `/chat/sessions/{id}/messages` | *multipart*: `text` (required unless image, ≤2000 chars), `image` (opt) | Returns `{ user_message, assistant_message }` | `MESSAGE_CREATED` (201) |
| POST | `/chat/sessions/{id}/messages/stream` | same *multipart* | SSE stream (below) | — |
| GET | `/chat/suggestions` | `?scan_id=` opt | 4 starter prompts (static + context-aware), e.g. "Is this meal good for muscle gain?" | `OK` |

A new session gets an auto title from the first user message (first ~6 words) if none was given.

**SSE events** (`text/event-stream`), each `data:` is JSON:
```
event: user_message   data: {ChatMessage}
event: tool           data: {"name": "get_daily_intake", "summary": "Checking today's intake…"}
event: delta          data: {"text": "partial text"}
event: done           data: {ChatMessage}          # final assistant message as saved
event: error          data: {"code": "AI_UNAVAILABLE", "message": "..."}
```

Chat errors: `EMPTY_MESSAGE` (400), `INVALID_IMAGE`, `FILE_TOO_LARGE`, `AI_UNAVAILABLE`, `RATE_LIMITED`, `NOT_FOUND`.

---

## Error code catalogue
`VALIDATION_ERROR` 422 · `UNAUTHORIZED` 401 · `INVALID_CREDENTIALS` 401 · `EMAIL_TAKEN` 409 · `NOT_FOUND` 404 · `INVALID_IMAGE` 400 · `FILE_TOO_LARGE` 413 · `NOT_FOOD` 422 · `EMPTY_MESSAGE` 400 · `ALREADY_LOGGED` 409 · `RATE_LIMITED` 429 · `AI_UNAVAILABLE` 503 · `AI_BAD_RESPONSE` 502 (Gemini JSON failed validation twice) · `INTERNAL_ERROR` 500 (generic message, never a stack trace).

## OpenAPI
- Every route has `summary`, `description`, `response_model` (the envelope generic), and **examples** from the fixtures.
- Tags: `system, auth, users, scans, intake, insights, chat`.
- Export `openapi.json` to `docs/openapi.json` at the end of the build (script or test).
