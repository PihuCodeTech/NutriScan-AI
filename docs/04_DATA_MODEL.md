# 04 — Data Model

SQLAlchemy 2.0 declarative models, async. UUID primary keys (stored as `String(36)` so SQLite and Postgres behave the same). All tables have `created_at`, and `updated_at` where rows change. Use JSON columns (`sqlalchemy.JSON`) for nutrient objects and small lists. First Alembic migration creates everything.

## Tables

### `users`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| email | str unique, indexed | lower-cased |
| password_hash | str | bcrypt |
| name | str | |
| created_at | datetime | |

### `profiles` (1:1 users)
| col | type | notes |
|---|---|---|
| user_id | uuid pk, fk users (cascade) | |
| age, sex, height_cm, weight_kg | nullable | |
| activity_level, goal, diet_type | str enums, nullable | |
| allergies, conditions | JSON list | default `[]` |
| country | str | default `IN` |
| timezone | str | default `Asia/Kolkata` |
| updated_at | datetime | |

### `scans`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | fk users, indexed | |
| status | str | `completed` / `rejected` |
| image_path | str | relative to `STORAGE_DIR` |
| image_sha256 | str, indexed | |
| description | str nullable | |
| meal_type | str | |
| meal_name | str nullable | |
| classifier_model | str nullable | |
| classifier_predictions | JSON nullable | list of `{label, display_name, score}` |
| ai_model | str | the Gemini model that actually answered |
| totals | JSON | Nutrients |
| health | JSON | Health object |
| raw_ai_response | JSON nullable | the validated Gemini output, for debugging |
| latency_ms | int | |
| logged_intake_id | fk intake_entries nullable | |
| created_at, updated_at | datetime | |

### `scan_items`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| scan_id | fk scans (cascade), indexed | |
| position | int | display order |
| name, canonical_name | str | |
| quantity_g | float | |
| serving_description | str nullable | |
| confidence | str | high / medium / low |
| source | str | ai / user_edit / user_added |
| nutrients | JSON | Nutrients for `quantity_g` |
| nutrients_per_100g | JSON | derived at creation; used for linear rescaling on gram edits |

### `intake_entries`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | fk, indexed | |
| source | str | scan / description / manual / chat |
| scan_id | fk scans nullable (set null on delete) | |
| name | str | |
| meal_type | str | |
| eaten_at | datetime, indexed | |
| local_date | date, indexed | computed from `eaten_at` + profile timezone; used by daily queries |
| items | JSON | list of FoodItem snapshots |
| totals | JSON | Nutrients |
| created_at | datetime | |

### `chat_sessions`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | fk, indexed | |
| title | str | |
| scan_id | fk scans nullable (set null) | |
| created_at, updated_at | datetime | `updated_at` bumps on every message |

### `chat_messages`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| session_id | fk chat_sessions (cascade), indexed | |
| role | str | user / assistant |
| content | text | |
| image_path | str nullable | |
| tool_calls | JSON nullable | `[{name, args, summary, result}]`; `result` is stored but not exposed by the API |
| ai_model | str nullable | |
| created_at | datetime | |

### `insight_cache`
| col | type | notes |
|---|---|---|
| id | uuid pk | |
| user_id | fk | |
| date | date | |
| totals_hash | str | sha256 of the day's totals JSON |
| payload | JSON | |
| unique | (user_id, date, totals_hash) | |

## Ownership rule
Every query on scans, intake, chat and insights is filtered by `user_id = current_user.id`. Accessing another user's resource returns **404**, not 403.
