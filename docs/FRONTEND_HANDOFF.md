# Frontend handoff — NutriScan AI API

Everything the frontend needs to build against this backend. The interactive reference is at **`/docs`**
(Swagger UI) and the machine-readable schema is [`docs/openapi.json`](openapi.json). Every example below was
generated from the running API in mock mode (`python scripts/generate_examples.py` → [`docs/examples/`](examples)).

## 1. Base URL and running the backend locally

- Base URL: **`http://localhost:8000/api/v1`** (production: whatever `PUBLIC_BASE_URL` is set to, + `/api/v1`).
- Run it with **no Gemini key and no model download** (deterministic fixtures):

  ```bash
  python3.11 -m venv .venv && source .venv/bin/activate
  pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements.txt
  cp .env.example .env        # then set MOCK_AI=true in .env
  uvicorn app.main:app --reload
  python scripts/seed_demo.py # optional: demo@nutriscan.app / demo12345 with 3 days of meals
  ```

- Mock-mode behaviour you can rely on: scans return a "Rajma Chawal Plate" (3 items); a scan `description`
  containing `not food` → `422 NOT_FOOD`; describe-text splits on commas/"and"; chat messages containing
  **"today"** call `get_daily_intake`, messages containing **"log"** call `log_meal` (e.g. "log 2 roti and dal
  for dinner"), others get a canned answer. SSE streams in ~5 `delta` chunks.
- CORS is open (`*`) by default; restrict with `CORS_ORIGINS`.

## 2. Auth

1. `POST /auth/register` `{email, password (≥ 8), name}` → `201 REGISTERED`, or `POST /auth/login`
   `{email, password}` → `200 LOGGED_IN`. Both return `{access_token, token_type: "bearer", user}`.
2. Send `Authorization: Bearer <access_token>` on every call except `/health`, `/meta` and `/auth/*`.
3. Tokens last **7 days**. There is no refresh token: on any **`401 UNAUTHORIZED`**, clear the token and send
   the user to login.

```json
{
  "success": true,
  "code": "REGISTERED",
  "message": "Account created",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIs…",
    "token_type": "bearer",
    "user": {
      "id": "130ac3a6-b336-400b-a8a3-f4e9fc7ef64b",
      "email": "asha@example.com",
      "name": "Asha",
      "profile": {
        "age": null,
        "sex": null,
        "height_cm": null,
        "weight_kg": null,
        "activity_level": null,
        "goal": null,
        "diet_type": null,
        "allergies": [],
        "conditions": [],
        "country": "IN",
        "timezone": "Asia/Kolkata"
      },
      "onboarding_complete": false
    }
  }
}
```

## 3. The envelope and errors

Every response — success or error — has the same shape:

```json
{ "success": true, "code": "SCAN_CREATED", "message": "Food analysed", "data": { } }
{ "success": false, "code": "NOT_FOOD", "message": "No food detected in the image.", "data": null, "details": { } }
```

- Branch on **`code`** (stable, machine-readable), show **`message`** (human-readable, safe to display).
- `details` is optional extra context: field errors for `VALIDATION_ERROR`
  (`[{loc: ["body","email"], msg, type}]` → show next to the field), `{scan_id, reason}` for `NOT_FOOD`.
- Every response has an `X-Request-ID` header — include it in bug reports.

| code | HTTP | When | Suggested UI |
|---|---|---|---|
| `VALIDATION_ERROR` | 422 | bad/missing fields | inline field errors from `details` |
| `UNAUTHORIZED` | 401 | missing/expired/invalid token | log out → login screen |
| `INVALID_CREDENTIALS` | 401 | wrong email/password | "Incorrect email or password" |
| `EMAIL_TAKEN` | 409 | register with an existing email | offer login instead |
| `NOT_FOUND` | 404 | unknown id, or someone else's resource | "Not found", go back |
| `INVALID_IMAGE` | 400 | not a JPEG/PNG/WebP, or unreadable | ask for another photo |
| `FILE_TOO_LARGE` | 413 | over `max_upload_mb` (from `/meta`) | compress/resize before upload |
| `NOT_FOOD` | 422 | no food in the photo / text | friendly "we couldn't spot food" + retake |
| `EMPTY_MESSAGE` | 400 | chat message with no text and no image | disable send button |
| `ALREADY_LOGGED` | 409 | scan already added to intake | show "Added ✓" state |
| `RATE_LIMITED` | 429 | too many AI calls (default 20/min per endpoint) | "Slow down a moment", retry later |
| `AI_UNAVAILABLE` | 503 | Gemini failed after retries + fallback. `details.reason`: `not_configured`, `auth` (key rejected), `quota`, `model`, `timeout`, `network`, `bad_request`, `unavailable` | Show `message` (it says what went wrong) + retry button for `quota`/`timeout`/`unavailable` |
| `AI_BAD_RESPONSE` | 502 | Gemini returned invalid data twice | same as above |
| `INTERNAL_ERROR` | 500 | unexpected server error (no details leak) | generic error + retry |
| `METHOD_NOT_ALLOWED` | 405 | wrong HTTP method | (developer error) |

```json
{
  "success": false,
  "code": "NOT_FOOD",
  "message": "No food detected in the image.",
  "data": null,
  "details": {
    "scan_id": "6499520d-a9ca-4f99-bb87-cd6bb8898eea",
    "reason": "The image does not appear to contain food."
  }
}
```

## 4. Don't hard-code: `GET /meta`

Fetch once at startup (no auth). It gives nutrient keys with **labels, units and decimals**, meal/diet/
activity/goal/sex options with display labels, **health label thresholds and colours**, meal shares, the
**disclaimer text** and **`max_upload_mb`**. Nutrients are always the same 8 keys:
`calories` (kcal), `protein_g`, `carbohydrates_g`, `fat_g`, `saturated_fat_g`, `fiber_g`, `sugar_g` (g),
`sodium_mg` (mg). Calories and sodium are whole numbers; the rest have 1 decimal.
Health: **≥ 75 good/green · 50–74 moderate/amber · < 50 needs_attention/red**.

<details><summary>/meta response</summary>

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "nutrients": [
      {
        "key": "calories",
        "label": "Calories",
        "unit": "kcal",
        "kind": "goal",
        "decimals": 0
      },
      {
        "key": "protein_g",
        "label": "Protein",
        "unit": "g",
        "kind": "goal",
        "decimals": 1
      },
      {
        "key": "carbohydrates_g",
        "label": "Carbohydrates",
        "unit": "g",
        "kind": "goal",
        "decimals": 1
      },
      {
        "key": "fat_g",
        "label": "Fat",
        "unit": "g",
        "kind": "goal",
        "decimals": 1
      },
      {
        "key": "saturated_fat_g",
        "label": "Saturated fat",
        "unit": "g",
        "kind": "limit",
        "decimals": 1
      },
      {
        "key": "fiber_g",
        "label": "Fibre",
        "unit": "g",
        "kind": "goal",
        "decimals": 1
      },
      {
        "key": "sugar_g",
        "label": "Sugar",
        "unit": "g",
        "kind": "limit",
        "decimals": 1
      },
      {
        "key": "sodium_mg",
        "label": "Sodium",
        "unit": "mg",
        "kind": "limit",
        "decimals": 0
      }
    ],
    "meal_types": [
      {
        "value": "breakfast",
        "label": "Breakfast"
      },
      {
        "value": "lunch",
        "label": "Lunch"
      },
      {
        "value": "dinner",
        "label": "Dinner"
      },
      {
        "value": "snack",
        "label": "Snack"
      }
    ],
    "diet_types": [
      {
        "value": "veg",
        "label": "Vegetarian"
      },
      {
        "value": "eggetarian",
        "label": "Eggetarian"
      },
      {
        "value": "non_veg",
        "label": "Non-vegetarian"
      },
      {
        "value": "vegan",
        "label": "Vegan"
      }
    ],
    "activity_levels": [
      {
        "value": "sedentary",
        "label": "Sedentary (little or no exercise)"
      },
      {
        "value": "light",
        "label": "Light (1–3 days/week)"
      },
      {
        "value": "moderate",
        "label": "Moderate (3–5 days/week)"
      },
      {
        "value": "active",
        "label": "Active (6–7 days/week)"
      },
      {
        "value": "very_active",
        "label": "Very active (hard exercise or physical job)"
      }
    ],
    "goals": [
      {
        "value": "lose",
        "label": "Lose weight"
      },
      {
        "value": "maintain",
        "label": "Maintain"
      },
      {
        "value": "gain",
        "label": "Gain weight / muscle"
      }
    ],
    "sexes": [
      {
        "value": "male",
        "label": "Male"
      },
      {
        "value": "female",
        "label": "Female"
      },
      {
        "value": "other",
        "label": "Other / prefer not to say"
      }
    ],
    "health_labels": [
      {
        "label": "good",
        "color": "green",
        "min_score": 75,
        "max_score": 100,
        "display": "Good"
      },
      {
        "label": "moderate",
        "color": "amber",
        "min_score": 50,
        "max_score": 74,
        "display": "Moderate"
      },
      {
        "label": "needs_attention",
        "color": "red",
        "min_score": 0,
        "max_score": 49,
        "display": "Needs attention"
      }
    ],
    "meal_shares": {
      "breakfast": 0.25,
      "lunch": 0.35,
      "dinner": 0.3,
      "snack": 0.1
    },
    "disclaimer": "Estimates only — not medical advice.",
    "max_upload_mb": 8.0,
    "accepted_image_types": [
      "image/jpeg",
      "image/png",
      "image/webp"
    ]
  }
}
```
</details>

## 5. Screens and the calls they make

### Onboarding / profile
1. `PUT /users/me/profile` — all fields optional, send only what changed (partial update). Fields: `age`
   (13–100), `sex`, `height_cm`, `weight_kg`, `activity_level`, `goal`, `diet_type`, `allergies[]`,
   `conditions[]`, `country`, `timezone` (IANA, default `Asia/Kolkata`).
2. `GET /users/me/targets` — daily targets. `basis: "default"` means the profile is incomplete (show a
   "complete your profile for personalised targets" nudge); `GET /users/me` → `onboarding_complete`.

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "calories": 1770.0,
    "protein_g": 55.0,
    "carbohydrates_g": 254.8,
    "fat_g": 59.0,
    "saturated_fat_g": 19.7,
    "fiber_g": 26.6,
    "sugar_g": 44.2,
    "sodium_mg": 2000.0,
    "basis": "profile",
    "explanation": "Mifflin–St Jeor BMR 1289 kcal × activity factor = TDEE 1772 kcal, adjusted for your goal (never below max(1200, BMR)). Protein by body weight; fat 30% and saturated fat 10% of calories; fibre 15 g per 1000 kcal; sugar ≤10% of calories; sodium ≤2000 mg.",
    "bmr": 1289.0,
    "tdee": 1772.4,
    "goal_nutrients": [
      "calories",
      "protein_g",
      "carbohydrates_g",
      "fat_g",
      "fiber_g"
    ],
    "limit_nutrients": [
      "saturated_fat_g",
      "sugar_g",
      "sodium_mg"
    ]
  }
}
```

### Scan screen
1. `POST /scans` — **multipart/form-data**: `image` (required), `description` (optional, ≤ 300 chars),
   `meal_type` (optional; defaults from the user's local time). Returns `201 SCAN_CREATED` with a `ScanResult`.
   Typical latency is a few seconds — show a progress state.
2. Render: `meal_name`, `items[]` (name, `serving_description`, grams, calories, `confidence` → e.g. a "?"
   badge for `low`), `totals`, `health.score` with `health.color`, `health.flags` as chips
   (`message`, and `value` vs `meal_target`), `health.tips`, and `health.disclaimer`.
   `classifier.predictions` is the transfer-learned model's guess — optional "Model guess vs final analysis"
   UI. `classifier` can be `null`.
3. Edit portions: `PATCH /scans/{id}/items` with `{"items": [...]}` — `{id, quantity_g}` rescales,
   `{id, name}` renames (re-estimated), `{id, remove: true}` removes, `{name, quantity_g}` without `id` adds.
   Returns the updated `ScanResult` (totals, score, flags recomputed; tips kept).
4. "Refresh tips" → `POST /scans/{id}/tips`.
5. "Add to today" → `POST /scans/{id}/log` (optional body `{meal_type, eaten_at}`) → `201 INTAKE_LOGGED` with
   an `IntakeEntry`. A second call → `409 ALREADY_LOGGED`; use `logged_intake_id` on the scan to show "Added ✓".
6. "Ask AI about this meal" → `POST /chat/sessions` with `{"scan_id": "<id>"}` (see Chat).
7. History: `GET /scans?page=1&page_size=20[&date=YYYY-MM-DD]` (summaries), `GET /scans/{id}`,
   `DELETE /scans/{id}`.

`ScanResult`:
```json
{
  "success": true,
  "code": "SCAN_CREATED",
  "message": "Food analysed",
  "data": {
    "id": "47af6ca0-d296-4454-bd68-ecd40486b56a",
    "status": "completed",
    "image_url": "http://localhost:8000/media/2026/09/92a98457-2d55-4477-9402-1c9823e57624.jpg",
    "meal_name": "Rajma Chawal Plate",
    "meal_type": "lunch",
    "description": "hostel lunch",
    "classifier": {
      "model": "nateraw/food",
      "predictions": [
        {
          "label": "chicken_curry",
          "display_name": "Chicken Curry",
          "score": 0.62
        },
        {
          "label": "samosa",
          "display_name": "Samosa",
          "score": 0.11
        },
        {
          "label": "falafel",
          "display_name": "Falafel",
          "score": 0.05
        }
      ]
    },
    "items": [
      {
        "id": "ce114a9e-03a3-4ff3-bd0b-b1d414ee77f6",
        "name": "Rajma",
        "canonical_name": "kidney_bean_curry",
        "quantity_g": 150.0,
        "serving_description": "1 katori (~150 g)",
        "confidence": "high",
        "source": "ai",
        "nutrients": {
          "calories": 215.0,
          "protein_g": 10.5,
          "carbohydrates_g": 30.0,
          "fat_g": 6.0,
          "saturated_fat_g": 1.0,
          "fiber_g": 9.0,
          "sugar_g": 1.5,
          "sodium_mg": 480.0
        }
      },
      {
        "id": "9c000bb4-7db4-4014-9d7f-a86d08f70e5f",
        "name": "Steamed Rice",
        "canonical_name": "steamed_rice",
        "quantity_g": 150.0,
        "serving_description": "1 cup cooked (~150 g)",
        "confidence": "high",
        "source": "ai",
        "nutrients": {
          "calories": 195.0,
          "protein_g": 4.0,
          "carbohydrates_g": 42.0,
          "fat_g": 0.4,
          "saturated_fat_g": 0.1,
          "fiber_g": 0.6,
          "sugar_g": 0.1,
          "sodium_mg": 5.0
        }
      },
      {
        "id": "434f9587-c7cd-4b20-b103-9b6175e36e70",
        "name": "Onion Salad",
        "canonical_name": "onion_salad",
        "quantity_g": 50.0,
        "serving_description": "small side (~50 g)",
        "confidence": "medium",
        "source": "ai",
        "nutrients": {
          "calories": 22.0,
          "protein_g": 0.6,
          "carbohydrates_g": 5.0,
          "fat_g": 0.1,
          "saturated_fat_g": 0.0,
          "fiber_g": 1.0,
          "sugar_g": 2.2,
          "sodium_mg": 60.0
        }
      }
    ],
    "totals": {
      "calories": 432.0,
      "protein_g": 15.1,
      "carbohydrates_g": 77.0,
      "fat_g": 6.5,
      "saturated_fat_g": 1.1,
      "fiber_g": 10.6,
      "sugar_g": 3.8,
      "sodium_mg": 545.0
    },
    "health": {
      "score": 93,
      "label": "good",
      "color": "green",
      "flags": [],
      "tips": [
        "Add a bowl of curd or a boiled egg for extra protein.",
        "Great fibre from the rajma — keep the salad and go easy on extra salt."
      ],
      "disclaimer": "Estimates only — not medical advice."
    },
    "ai_model": "mock-gemini",
    "logged_intake_id": null,
    "created_at": "2026-09-28T10:36:45.374338Z"
  }
}
```

`GET /scans` (page of summaries):
```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "items": [
      {
        "id": "6499520d-a9ca-4f99-bb87-cd6bb8898eea",
        "status": "rejected",
        "image_url": "http://localhost:8000/media/2026/09/8dca561c-d897-47dc-8c8f-6ef496dc568f.jpg",
        "meal_name": null,
        "meal_type": "snack",
        "totals": {
          "calories": 0.0
        },
        "health": null,
        "created_at": "2026-09-28T10:36:45.385095Z"
      }
    ],
    "page": 1,
    "page_size": 20,
    "total": 2
  }
}
```

### Home / dashboard
- `GET /intake/daily[?date=YYYY-MM-DD]` — the day's entries, `totals`, `targets`, `remaining`,
  `percent_of_target` (ints, for progress rings), `health_status` (`on_track|over|under|no_data`) and
  `status_flags` (chips).
- `GET /insights/daily[?date=]` — `headline`, `summary`, exactly 3 `tips`, `health_status`, `disclaimer`.
  Cached server-side until the day's totals change, so it's cheap to call on every dashboard open.
- `GET /intake/summary?days=7` — `days[]` (zero-filled, oldest → today) with `totals` and `calorie_percent`
  for a bar chart, `averages` (over logged days), `streak_days_logged`, `top_foods`.
- Quick add: `POST /intake/describe` `{text, meal_type?, log?}` → preview `{meal_name, items, totals, health}`;
  with `log: true` it also returns `intake_entry`. Manual entry with known numbers: `POST /intake`.
  Delete: `DELETE /intake/{id}`.

`GET /intake/daily`:
```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "date": "2026-09-28",
    "health_status": "on_track",
    "entries": [
      {
        "id": "9239fd02-24bf-48b1-8768-2f7a8af7cbbe",
        "source": "scan",
        "scan_id": "47af6ca0-d296-4454-bd68-ecd40486b56a",
        "name": "Rajma Chawal Plate",
        "meal_type": "lunch",
        "eaten_at": "2026-09-28T10:36:45.443852Z",
        "items": [
          {
            "id": "ce114a9e-03a3-4ff3-bd0b-b1d414ee77f6",
            "name": "Rajma",
            "canonical_name": "kidney_bean_curry",
            "quantity_g": 200.0,
            "serving_description": "200 g (edited)",
            "confidence": "high",
            "source": "user_edit",
            "nutrients": {
              "calories": 287.0,
              "protein_g": 14.0,
              "carbohydrates_g": 40.0,
              "fat_g": 8.0,
              "saturated_fat_g": 1.3,
              "fiber_g": 12.0,
              "sugar_g": 2.0,
              "sodium_mg": 640.0
            }
          }
        ],
        "totals": {
          "calories": 565.0,
          "protein_g": 22.1,
          "carbohydrates_g": 91.7,
          "fat_g": 11.8,
          "saturated_fat_g": 3.5,
          "fiber_g": 13.6,
          "sugar_g": 9.0,
          "sodium_mg": 751.0
        }
      },
      {
        "id": "d6ce971e-a89f-4a1b-a689-501ae696a603",
        "source": "description",
        "scan_id": null,
        "name": "Roti & Dal & Lassi",
        "meal_type": "dinner",
        "eaten_at": "2026-09-28T10:36:45.454197Z",
        "items": [
          {
            "id": "3aae4f24-83c3-4a25-9bae-e5f85270ef9c",
            "name": "Roti",
            "canonical_name": "roti",
            "quantity_g": 80.0,
            "serving_description": "2 serving(s) (~80 g)",
            "confidence": "high",
            "source": "ai",
            "nutrients": {
              "calories": 211.0,
              "protein_g": 6.8,
              "carbohydrates_g": 36.8,
              "fat_g": 4.2,
              "saturated_fat_g": 0.8,
              "fiber_g": 5.2,
              "sugar_g": 1.2,
              "sodium_mg": 280.0
            }
          }
        ],
        "totals": {
          "calories": 601.0,
          "protein_g": 23.6,
          "carbohydrates_g": 90.3,
          "fat_g": 16.5,
          "saturated_fat_g": 6.2,
          "fiber_g": 10.4,
          "sugar_g": 32.7,
          "sodium_mg": 812.0
        }
      }
    ],
    "totals": {
      "calories": 1166.0,
      "protein_g": 45.7,
      "carbohydrates_g": 182.0,
      "fat_g": 28.3,
      "saturated_fat_g": 9.7,
      "fiber_g": 24.0,
      "sugar_g": 41.7,
      "sodium_mg": 1563.0
    },
    "targets": {
      "calories": 1770.0,
      "protein_g": 55.0,
      "carbohydrates_g": 254.8,
      "fat_g": 59.0,
      "saturated_fat_g": 19.7,
      "fiber_g": 26.6,
      "sugar_g": 44.2,
      "sodium_mg": 2000.0
    },
    "remaining": {
      "calories": 604.0,
      "protein_g": 9.3,
      "carbohydrates_g": 72.8,
      "fat_g": 30.7,
      "saturated_fat_g": 10.0,
      "fiber_g": 2.6,
      "sugar_g": 2.5,
      "sodium_mg": 437.0
    },
    "percent_of_target": {
      "calories": 66,
      "protein_g": 83,
      "carbohydrates_g": 71,
      "fat_g": 48,
      "saturated_fat_g": 49,
      "fiber_g": 90,
      "sugar_g": 94,
      "sodium_mg": 78
    },
    "status_flags": []
  }
}
```

`IntakeEntry` (from `POST /scans/{id}/log`):
```json
{
  "success": true,
  "code": "INTAKE_LOGGED",
  "message": "Added to your intake",
  "data": {
    "id": "9239fd02-24bf-48b1-8768-2f7a8af7cbbe",
    "source": "scan",
    "scan_id": "47af6ca0-d296-4454-bd68-ecd40486b56a",
    "name": "Rajma Chawal Plate",
    "meal_type": "lunch",
    "eaten_at": "2026-09-28T10:36:45.443852Z",
    "items": [
      {
        "id": "ce114a9e-03a3-4ff3-bd0b-b1d414ee77f6",
        "name": "Rajma",
        "canonical_name": "kidney_bean_curry",
        "quantity_g": 200.0,
        "serving_description": "200 g (edited)",
        "confidence": "high",
        "source": "user_edit",
        "nutrients": {
          "calories": 287.0,
          "protein_g": 14.0,
          "carbohydrates_g": 40.0,
          "fat_g": 8.0,
          "saturated_fat_g": 1.3,
          "fiber_g": 12.0,
          "sugar_g": 2.0,
          "sodium_mg": 640.0
        }
      },
      {
        "id": "9c000bb4-7db4-4014-9d7f-a86d08f70e5f",
        "name": "Steamed Rice",
        "canonical_name": "steamed_rice",
        "quantity_g": 150.0,
        "serving_description": "1 cup cooked (~150 g)",
        "confidence": "high",
        "source": "ai",
        "nutrients": {
          "calories": 195.0,
          "protein_g": 4.0,
          "carbohydrates_g": 42.0,
          "fat_g": 0.4,
          "saturated_fat_g": 0.1,
          "fiber_g": 0.6,
          "sugar_g": 0.1,
          "sodium_mg": 5.0
        }
      },
      {
        "id": "434f9587-c7cd-4b20-b103-9b6175e36e70",
        "name": "Onion Salad",
        "canonical_name": "onion_salad",
        "quantity_g": 50.0,
        "serving_description": "small side (~50 g)",
        "confidence": "medium",
        "source": "ai",
        "nutrients": {
          "calories": 22.0,
          "protein_g": 0.6,
          "carbohydrates_g": 5.0,
          "fat_g": 0.1,
          "saturated_fat_g": 0.0,
          "fiber_g": 1.0,
          "sugar_g": 2.2,
          "sodium_mg": 60.0
        }
      },
      {
        "id": "a90468fc-1379-4344-9566-9e2844d6c3f2",
        "name": "Curd",
        "canonical_name": "curd",
        "quantity_g": 100.0,
        "serving_description": "100 g (added)",
        "confidence": "high",
        "source": "user_added",
        "nutrients": {
          "calories": 61.0,
          "protein_g": 3.5,
          "carbohydrates_g": 4.7,
          "fat_g": 3.3,
          "saturated_fat_g": 2.1,
          "fiber_g": 0.0,
          "sugar_g": 4.7,
          "sodium_mg": 46.0
        }
      }
    ],
    "totals": {
      "calories": 565.0,
      "protein_g": 22.1,
      "carbohydrates_g": 91.7,
      "fat_g": 11.8,
      "saturated_fat_g": 3.5,
      "fiber_g": 13.6,
      "sugar_g": 9.0,
      "sodium_mg": 751.0
    }
  }
}
```

`GET /insights/daily`:
```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "date": "2026-09-28",
    "headline": "Nice work logging today!",
    "summary": "You're at about 66% of your calorie target so far. Keep meals balanced with protein and fibre.",
    "tips": [
      "Add curd, dal or eggs to your next meal for protein.",
      "Snack on fruit or roasted chana instead of chips.",
      "Keep a water bottle at your desk and sip through the day."
    ],
    "health_status": "on_track",
    "disclaimer": "Estimates only — not medical advice."
  }
}
```

`GET /intake/summary?days=7`:
```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "data": {
    "days": [
      {
        "date": "2026-09-27",
        "totals": {
          "calories": 0.0,
          "protein_g": 0.0,
          "carbohydrates_g": 0.0,
          "fat_g": 0.0,
          "saturated_fat_g": 0.0,
          "fiber_g": 0.0,
          "sugar_g": 0.0,
          "sodium_mg": 0.0
        },
        "calorie_percent": 0,
        "entries": 0
      },
      {
        "date": "2026-09-28",
        "totals": {
          "calories": 1166.0,
          "protein_g": 45.7,
          "carbohydrates_g": 182.0,
          "fat_g": 28.3,
          "saturated_fat_g": 9.7,
          "fiber_g": 24.0,
          "sugar_g": 41.7,
          "sodium_mg": 1563.0
        },
        "calorie_percent": 66,
        "entries": 2
      }
    ],
    "averages": {
      "calories": 1166.0,
      "protein_g": 45.7,
      "carbohydrates_g": 182.0,
      "fat_g": 28.3,
      "saturated_fat_g": 9.7,
      "fiber_g": 24.0,
      "sugar_g": 41.7,
      "sodium_mg": 1563.0
    },
    "days_logged": 1,
    "streak_days_logged": 1,
    "top_foods": [
      {
        "name": "Rajma",
        "count": 1
      },
      {
        "name": "Steamed Rice",
        "count": 1
      },
      {
        "name": "Onion Salad",
        "count": 1
      },
      {
        "name": "Curd",
        "count": 1
      },
      {
        "name": "Roti",
        "count": 1
      }
    ]
  }
}
```

### Chat
1. `GET /chat/suggestions[?scan_id=]` → 4 starter prompts (meal-specific when a scan is linked).
2. `POST /chat/sessions` `{title?, scan_id?}` → session. Without a title, the first message's first words
   become the title. List with `GET /chat/sessions` (includes `last_message_preview`), open with
   `GET /chat/sessions/{id}` (`messages` oldest first), rename with `PATCH`, delete with `DELETE`.
3. Send: **multipart** `text` (≤ 2000 chars) and/or `image`.
   - Non-streaming: `POST /chat/sessions/{id}/messages` → `{user_message, assistant_message}`.
   - Streaming (recommended): `POST /chat/sessions/{id}/messages/stream` → `text/event-stream`.
4. `content` is **Markdown** (bold, bullet lists). Assistant messages may include `tool_calls`
   (`[{name, args, summary}]`) — render as small "Checked your intake for 2026-09-28" chips. When a
   `log_meal` tool call appears, refresh the dashboard data.
5. Images in chat come back as `image_url` on the user message.

`ChatMessage` exchange:
```json
{
  "success": true,
  "code": "MESSAGE_CREATED",
  "message": "Message sent",
  "data": {
    "user_message": {
      "id": "9b5ed734-3993-458c-9b2d-b63af242cbae",
      "role": "user",
      "content": "How did I do today?",
      "image_url": null,
      "tool_calls": null,
      "created_at": "2026-09-28T10:36:45.491087Z"
    },
    "assistant_message": {
      "id": "9df1b2aa-fd5b-48a1-9d95-f565bb3f30b1",
      "role": "assistant",
      "content": "So far today you've had about **1166 kcal** of your 1770 kcal target, with 46 g protein.\n- Add curd, dal or eggs for protein\n- Keep dinner light and balanced",
      "image_url": null,
      "tool_calls": [
        {
          "name": "get_daily_intake",
          "args": {},
          "summary": "Checked your intake for 2026-09-28"
        }
      ],
      "created_at": "2026-09-28T10:36:45.496521Z"
    }
  }
}
```

**SSE events** (each `data:` line is JSON):

| event | data | UI |
|---|---|---|
| `user_message` | `ChatMessage` (as saved) | replace the optimistic bubble |
| `tool` | `{name, summary}` | show a transient "Checking today's intake…" indicator |
| `delta` | `{text}` | append to the assistant bubble |
| `done` | `ChatMessage` (final, as saved) | replace the streamed bubble with this |
| `error` | `{code, message}` | show error + retry; nothing was saved for the assistant |

Validation problems (empty message, bad image, unknown session, rate limit) come back as a normal JSON
error envelope **before** the stream starts — check `response.ok` / the content type first.

```text
event: user_message
data: {"id": "db0e682e-62e5-493a-8732-6f9d837fb243", "role": "user", "content": "log a banana as snack", "image_url": null, "tool_calls": null, "created_at": "2026-09-28T10:36:45.501810Z"}

event: tool
data: {"name": "log_meal", "summary": "Logging your meal…"}

event: delta
data: {"text": "Done! I've log"}

event: delta
data: {"text": "ged **Banana**"}

event: delta
data: {"text": " (~115 kcal) t"}

event: delta
data: {"text": "o your snack. "}

event: delta
data: {"text": "Anything else?"}

event: done
data: {"id": "d8385886-896b-4acf-abcf-0a3c4a268381", "role": "assistant", "content": "Done! I've logged **Banana** (~115 kcal) to your snack. Anything else?", "image_url": null, "tool_calls": [{"name": "log_meal", "args": {"description": "a banana", "meal_type": "snack"}, "summary": "Logged Banana to your snack"}], "created_at": "2026-09-28T10:36:45.508565Z"}
```

`EventSource` can't POST multipart, so use `fetch` + a stream reader:

```ts
async function streamChat(sessionId: string, text: string, image: File | null, token: string,
                          on: (event: string, data: any) => void) {
  const form = new FormData();
  if (text) form.append("text", text);
  if (image) form.append("image", image);
  const res = await fetch(`${API}/chat/sessions/${sessionId}/messages/stream`, {
    method: "POST", headers: { Authorization: `Bearer ${token}` }, body: form,
  });
  if (!res.ok || !res.headers.get("content-type")?.startsWith("text/event-stream")) {
    throw await res.json();                      // error envelope: {success:false, code, message, ...}
  }
  const reader = res.body!.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let sep;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, sep); buffer = buffer.slice(sep + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1] ?? "message";
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (data) on(event, JSON.parse(data));
    }
  }
}
```

## 6. Images

- Upload JPEG, PNG or WebP up to `max_upload_mb` (8 MB). The server orients (EXIF), strips metadata, resizes to
  ≤ 1024 px and stores a JPEG — resizing on the client first makes uploads faster.
- All `image_url`s are **absolute** (built from `PUBLIC_BASE_URL`, served under `/media/…`) and need no auth
  header, so they can go straight into `<img src>`.

## 7. Conventions recap

- JSON is **snake_case**; ids are UUID strings; timestamps are ISO-8601 **UTC** (`…Z`); `date` params and
  fields are `YYYY-MM-DD` in the **user's timezone** (`profile.timezone`).
- Pagination: `?page=1&page_size=20` (max 100) → `data: {items, page, page_size, total}`.
- Show `disclaimer` ("Estimates only — not medical advice.") wherever AI estimates are shown.
