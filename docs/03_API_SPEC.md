
---

## Additions (2026-10 pass)

### New endpoints
- `POST /auth/guest` → `{access_token, token_type, user}` with `user.is_guest = true`. A throw-away account so
  people can use the AI without signing up. Rate-limited 30/hour per IP. Code `GUEST_CREATED` (201).
- `POST /recipes/suggest` (auth) → Gemini meal ideas from the user's ingredients.
  Body: `{ingredients: string[1..20], kitchen: "none"|"kettle"|"burner" = "burner", count: 1..5 = 3, note?: string}`.
  Returns `{meals: [{name, why, time_minutes, kitchen, ingredients, steps, nutrients}], ai_model, disclaimer}`.
  Nutrients are per serving and sanitised server-side. Code `RECIPES_SUGGESTED`.
- `GET /api/v1/media/{path}?exp=&sig=` → the uploaded image, only with a valid signature and unexpired `exp`.
  Not in the OpenAPI schema. The `/media` static mount was removed; `image_url` fields are signed URLs.

### Changed fields
- **FoodItem** (scans and intake items) gained `nutrition_source: "table" | "estimate"` — whether the nutrients
  came from the curated foods table or the AI estimate.
- **ScanResult** / scoring: the scan accepts an optional `meal_type` form field. When omitted, the score is
  computed against a neutral one-third-of-day share (so the same plate scores the same regardless of the time
  it was scanned); the stored `meal_type` is still a sensible label.
- **POST /scans/{id}/log** body accepts `is_street_food: bool = false`.
- **IntakeEntry** gained `is_street_food` and `is_home_cooked`. `POST /intake` accepts both.
- **Profile** gained `kitchen: "none"|"kettle"|"burner"` (default `burner`); `PUT /users/me/profile` accepts it.
- **GET /intake/summary** gained `street_free_streak_days`, `street_food_count`, `home_cooked_count`.
- **GET /users/me** → `user.is_guest`.
