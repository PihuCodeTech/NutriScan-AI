# 05 — AI Pipeline: Classifier, Gemini, Chatbot, Health Engine

## 1. Transfer-learned classifier (`app/services/classifier.py`)

**What it is:** `nateraw/food` on Hugging Face, a ViT-base model (`google/vit-base-patch16-224-in21k`, pretrained on ImageNet-21k) **fine-tuned on Food-101** (101 dishes, ~89% eval accuracy). This is the project's transfer-learning component. `ml/finetune_indian_food.py` (optional) shows the next step: fine-tuning it further on Indian dishes.

**Role in the pipeline:** fast, cheap first opinion. Its top-k predictions are passed to Gemini as **hints**, stored on the scan, and returned to the frontend (`classifier.predictions`) so the UI can show "Model guess vs final analysis". Gemini makes the final multi-item decision because Food-101 is single-label and Western-heavy.

**Implementation:**
```python
from transformers import pipeline

self._pipe = pipeline("image-classification", model=settings.CLASSIFIER_MODEL_ID, device=-1)  # CPU
preds = self._pipe(pil_image, top_k=settings.CLASSIFIER_TOP_K)
# -> [{"label": "chicken_curry", "score": 0.62}, ...]
```
- Load **once** in the FastAPI `lifespan` (in a thread). If loading fails (no internet, etc.), log a warning and mark the classifier `error`. Scans continue without hints.
- `predict()` runs in a threadpool. Return `[{label, display_name, score}]` where `display_name = label.replace("_", " ").title()`, and `score` is rounded to 3 decimals.
- `MOCK_AI=true` or `CLASSIFIER_ENABLED=false` → a mock or no-op classifier (never downloads weights in tests).
- Expose status for `/health`: `loaded | disabled | error`.

## 2. Gemini client (`app/services/llm/gemini_client.py`)

The **only** module that imports `google.genai`. It exposes an interface (a `Protocol`) implemented by both `GeminiClient` and `MockGeminiClient`:

```python
class LLMClient(Protocol):
    async def analyze_food_image(
        self, image: bytes, mime: str, *, hints: list[dict], user_ctx: str, description: str | None
    ) -> FoodAnalysisLLM: ...
    async def estimate_from_text(self, text: str, *, user_ctx: str) -> FoodAnalysisLLM: ...
    async def generate_tips(self, *, items: list[dict], totals: dict, flags: list[dict], user_ctx: str) -> TipsLLM: ...
    async def daily_insight(self, *, day_summary: dict, user_ctx: str) -> InsightLLM: ...
    async def chat_turn(
        self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec]
    ) -> ChatTurn: ...  # text and/or function_calls
    def chat_stream(
        self, *, system: str, history: list[ChatHistoryItem]
    ) -> AsyncIterator[str]: ...  # final answer streaming
    @property
    def last_model_used(self) -> str: ...
```

**SDK usage reference** (`pip install -U google-genai`; confirm against the installed version):
```python
from google import genai
from google.genai import types

client = genai.Client(api_key=settings.GEMINI_API_KEY)

# Structured multimodal call
resp = await client.aio.models.generate_content(
    model=model,
    contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt_text],
    config=types.GenerateContentConfig(
        system_instruction=SYSTEM_FOOD_ANALYST,
        temperature=0.2,
        response_mime_type="application/json",
        response_schema=FoodAnalysisLLM,  # a Pydantic model
    ),
)
data = resp.parsed or FoodAnalysisLLM.model_validate_json(resp.text)

# Function calling (manual loop; disable automatic calling)
config = types.GenerateContentConfig(
    system_instruction=system,
    tools=[
        types.Tool(function_declarations=[types.FunctionDeclaration(name=..., description=..., parameters=json_schema)])
    ],
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    temperature=0.6,
)
resp = await client.aio.models.generate_content(model=model, contents=contents, config=config)
resp.function_calls  # list of calls with .name and .args, or None
# append resp.candidates[0].content, then a Content holding types.Part.from_function_response(name=..., response={"result": ...})

# Streaming
async for chunk in await client.aio.models.generate_content_stream(model=model, contents=contents, config=config):
    yield chunk.text or ""
```
> Google's docs now also describe an "Interactions API". If `models.generate_content` is unavailable or deprecated in the installed SDK, switch to the equivalent there, **inside this file only**. Run `scripts/smoke_gemini.py` to confirm.

**Reliability rules:**
- Timeout `GEMINI_TIMEOUT_S`. On timeout, 429 or 5xx: retry once after ~1.5 s, then try `GEMINI_FALLBACK_MODEL` once, then raise `AppError("AI_UNAVAILABLE", 503)`.
- If structured output fails Pydantic validation: re-ask once with "Return ONLY valid JSON matching the schema", then raise `AI_BAD_RESPONSE` (502).
- Record `last_model_used`, which is saved on scans and messages.
- Never log image bytes or the API key. Log model, latency and token usage if available.

## 3. LLM output schemas (`app/services/llm/schemas.py`)
```python
Confidence = Literal["high", "medium", "low"]


class LLMNutrients(BaseModel):
    calories: float
    protein_g: float
    carbohydrates_g: float
    fat_g: float
    saturated_fat_g: float
    fiber_g: float
    sugar_g: float
    sodium_mg: float


class LLMFoodItem(BaseModel):
    name: str  # localised display name, e.g. "Rajma"
    canonical_name: str  # lowercase snake_case English, e.g. "kidney_bean_curry"
    quantity_g: float  # estimated edible weight in grams
    serving_description: str  # e.g. "1 katori (~150 g)"
    confidence: Confidence
    nutrients: LLMNutrients  # for quantity_g, NOT per 100 g


class FoodAnalysisLLM(BaseModel):
    is_food: bool
    rejection_reason: str | None = None
    meal_name: str | None = None
    items: list[LLMFoodItem] = []
    tips: list[str] = []  # 2–3 short tips (image and text analysis)


class TipsLLM(BaseModel):
    tips: list[str]


class InsightLLM(BaseModel):
    headline: str
    summary: str
    tips: list[str]
```
Gemini's `response_schema` may reject some Pydantic features (defaults, unions). If so, keep these models simple and do a second, stricter validation into the API schemas.

## 4. Prompts (`app/services/llm/prompts.py`)

### 4.1 `SYSTEM_FOOD_ANALYST`
```
You are a precise nutrition analyst for an app used by college students in hostels and shared flats,
mostly in India. You estimate what is on a plate and its nutrition from photos or descriptions.
Be realistic about Indian mess, canteen, street-food and home-style portions and cooking (oil, ghee, salt).
Return only data that matches the requested JSON schema.
```

### 4.2 Food image prompt (adapted from ScanMyFood's analyzeFoodImage)
```
USER CONTEXT:
{user_ctx}                       # country, diet_type, allergies, goal (one line each; "unknown" if missing)

IMAGE CLASSIFIER HINTS (a Food-101 model; it knows mostly Western dishes, so treat these as weak hints only):
{hints}                          # e.g. "chicken_curry (0.62), samosa (0.11), falafel (0.05)" or "none"

USER DESCRIPTION: {description or "none"}

TASK:
1. Decide if the image shows food or drink meant for eating. If not, set is_food=false, give a short
   rejection_reason, and leave items empty.
2. Identify EVERY distinct food/drink item visible (a thali may have 5–8 items: rice, roti, dal, sabzi,
   curd, salad, pickle, sweet). One entry per item. Do not merge distinct items.
3. For each item estimate the edible quantity in grams from visual cues: plate/katori/glass size, item
   height and spread, count of pieces. Don't mistake a zoomed-in container for a large one.
   Typical references: 1 roti ≈ 40 g, 1 katori dal/sabzi ≈ 150 g, 1 cup cooked rice ≈ 150 g,
   1 idli ≈ 40 g, 1 dosa ≈ 100 g, 1 samosa ≈ 60 g, 1 packet instant noodles (cooked) ≈ 250 g.
4. Give nutrients for the ESTIMATED QUANTITY (not per 100 g). Prefer values consistent with
   IFCT 2017 / Indian Nutrient Databank for Indian foods and USDA FoodData Central otherwise.
   Account for cooking oil/ghee typical of the preparation.
   Keep calories consistent with Atwater factors (protein 4, carbs 4, fat 9 kcal/g).
5. Use the common local name in the user's country for "name" (e.g. "Rajma", "Poha", "Chole"), and a
   lowercase snake_case English "canonical_name".
6. Set confidence per item: high (clearly visible, common dish), medium, low (occluded/ambiguous).
7. meal_name: a short friendly name for the whole plate (e.g. "Mess Lunch Thali").
8. tips: 2–3 short, practical, budget-friendly suggestions for a student about THIS meal
   (what to add, reduce or swap). Respect diet_type and allergies. No medical claims. ≤ 25 words each.
```

### 4.3 Text estimate prompt (`estimate_from_text`)
Same rules 2–8 applied to a description ("2 roti, dal and a glass of lassi"). Always `is_food=true` unless the text clearly isn't food. If quantities are missing, assume typical single servings and say so in `serving_description`.

### 4.4 Tips prompt (`generate_tips`)
Input: items (name, grams), totals, the backend's flags, user context. Output: 2–3 tips that address the flags first. Same style rules.

### 4.5 Daily insight prompt (`daily_insight`)
Input: the day's totals, targets, percentages, entries (names + meal types), the backend's `health_status`, user context. Output: `headline` (≤ 8 words, encouraging), `summary` (2 sentences), 3 tips for the rest of today or tomorrow. Never shame the user. With no data, gently encourage logging.

### 4.6 Chatbot system instruction (`build_chat_system`)
```
You are "NutriBuddy", a friendly nutrition assistant inside a food-scanner app for students living in
hostels or on their own (mostly in India). You help with: understanding meals and nutrition labels,
healthy choices at the mess/canteen/street stalls, cheap high-protein options, simple hostel-friendly
recipes (kettle/induction/no-cook), hydration, and building better eating habits.

Style: warm, concise (≤ 150 words unless asked for more), practical, specific to Indian food when relevant.
Use short bullet lists when giving options. Use the user's data when it helps; don't dump numbers.

Tools: call tools to read the user's intake, scans or profile instead of guessing. Only call log_meal when
the user explicitly asks to log/add/save something; if quantities are unclear, ask one quick question first.
When the user sends a food photo, identify the items and give approximate calories/macros, and offer
to log it.

Boundaries: you are not a doctor. No diagnoses, medication or treatment advice. For medical conditions
give general guidance and suggest a doctor or registered dietitian. Never encourage crash diets, skipping
meals, or eating below the user's safe minimum. If the user seems to struggle with disordered eating or
body image, respond with care, avoid numbers, and encourage talking to a professional or someone they trust.
Politely steer off-topic requests back to food, nutrition and healthy habits.
Respect diet type and allergies strictly.

USER CONTEXT (may be partial):
- Name: {name} | Diet: {diet_type} | Allergies: {allergies} | Goal: {goal} | Conditions: {conditions}
- Daily targets: {targets_short}
- Today so far ({date}): {today_totals_short} ({percent_calories}% of calories), meals logged: {meal_list}
{linked_scan_block}   # if the session has scan_id: meal name, items with grams, totals, score, flags
Current local time: {local_time}
```

## 5. Nutrition rules (`app/services/nutrition.py`)
- `sanitize(n)`: clamp negatives to 0; `saturated_fat_g ≤ fat_g`; `sugar_g ≤ carbohydrates_g`; `fiber_g ≤ carbohydrates_g`.
  **Atwater check:** `k = 4P + 4C + 9F`. If `|calories − k| / max(k, 1) > 0.25`, set `calories = k` and log a warning.
- `per_100g(item) = nutrients × 100 / quantity_g` (guard quantity 0). Stored on each item.
- `scale(item, new_g) = per_100g × new_g / 100`.
- `aggregate(items) → Nutrients`: field-wise sum, then round (calories and sodium to int, others 1 dp).
- Rename or add item in `PATCH /scans/{id}/items`: call `estimate_from_text("{grams} g {name}")` and take the first item's nutrients.

## 6. Health engine (`app/services/health_engine.py`)
All deterministic and unit-tested.

### 6.1 Daily targets
- **BMR (Mifflin–St Jeor):** male `10w + 6.25h − 5a + 5`; female `10w + 6.25h − 5a − 161`; other: mean of the two.
- **TDEE** = BMR × {sedentary 1.2, light 1.375, moderate 1.55, active 1.725, very_active 1.9}.
- **Calories:** lose `TDEE − 400`, maintain `TDEE`, gain `TDEE + 300`. **Floor = max(1200, BMR)**. Never target below the floor. Round to 10.
- **protein_g** = weight × (1.2 if goal in {lose, gain} else 1.0).
- **fat_g** = 30% kcal / 9 · **saturated_fat_g (limit)** = 10% kcal / 9.
- **carbohydrates_g** = (kcal − 4·protein − 9·fat) / 4.
- **fiber_g** = 15 g per 1000 kcal · **sugar_g (limit)** = 10% kcal / 4 · **sodium_mg (limit)** = 2000.
- Incomplete profile → defaults: 2000 kcal, protein 50, carbs 275, fat 67, sat fat 22, fiber 30, sugar 50, sodium 2000, with `basis = "default"` (otherwise `"profile"`).
- Classes: *goal nutrients* = calories, protein, carbs, fat, fiber; *limit nutrients* = saturated fat, sugar, sodium.

### 6.2 Meal score (0–100)
Meal share of daily targets: breakfast 0.25, lunch 0.35, dinner 0.30, snack 0.10. `meal_target = daily × share`, `r = value / meal_target`.

Start at 100 and subtract:
| Condition | Penalty | Flag |
|---|---|---|
| sodium r > 1 | `min(25, 25·(r−1))` | high sodium_mg |
| sugar r > 1 | `min(20, 20·(r−1))` | high sugar_g |
| saturated fat r > 1 | `min(15, 15·(r−1))` | high saturated_fat_g |
| calories r > 1.25 | `min(15, 20·(r−1.25))` | high calories |
| fat r > 1.3 | `min(10, 10·(r−1.3))` | high fat_g |
| protein r < 0.6 / 0.6–0.9 | 15 / 7 (halved for snacks) | low protein_g (only when r < 0.6) |
| fiber r < 0.5 / 0.5–0.8 | 10 / 5 (halved for snacks) | low fiber_g (only when r < 0.5) |

Clamp to 0–100 and round to int. Labels: ≥75 good/green, 50–74 moderate/amber, <50 needs_attention/red.
Flag messages are fixed templates, e.g. "High in salt for one meal", "Low in protein", "Low in fibre", "Sugary", "Heavy on calories for a {meal_type}".

### 6.3 Daily status
- `no_data`: no entries.
- `over`: calories > 110% of target, or any limit nutrient > 100%.
- `under`: calories < 85% **and** (the date is in the past, or local time ≥ 20:00).
- otherwise `on_track`.
- `remaining = max(target − total, 0)` for goal nutrients; for limit nutrients `remaining = target − total` (may be negative).
- `percent_of_target` per nutrient, rounded to int.

## 7. Chatbot (`app/services/chat/`)

### 7.1 Context building (`context.py`)
Each turn, build a fresh system instruction (§4.6) from: profile, targets, today's totals and meal list, and the linked scan (if any). Keep it under ~600 tokens.

### 7.2 History
- Send the last `CHAT_HISTORY_TURNS` messages (user and assistant text).
- Include image bytes **only for the current user message**. Earlier user images become the text marker `[user shared a photo]`.
- Tool traces from earlier turns are not replayed. Only the final assistant text is sent.

### 7.3 Tools (`tools.py`)
Each tool has a JSON-schema declaration, an async executor scoped to `current_user` and the db session, and a short human `summary` for the UI.
| Name | Params | Returns | UI summary |
|---|---|---|---|
| `get_user_profile` | – | profile + targets | "Checked your profile" |
| `get_daily_intake` | `date?: YYYY-MM-DD` | entries (name, meal_type, calories), totals, targets, remaining, status | "Checked your intake for {date}" |
| `get_intake_summary` | `days?: int (1–31, default 7)` | per-day calories, averages, top foods | "Looked at your last {days} days" |
| `get_recent_scans` | `limit?: int (1–10, default 5)` | id, meal_name, calories, score, created_at | "Looked at your recent scans" |
| `get_scan_details` | `scan_id: str` | items, totals, health | "Opened scan details" |
| `estimate_meal` | `description: str` | items + totals (not saved) | "Estimated nutrition" |
| `log_meal` | `description: str, meal_type: enum, eaten_at?: str` | the saved intake entry (source="chat") | "Logged {name} to your {meal_type}" |

Tool loop: at most `CHAT_MAX_TOOL_ROUNDS` rounds. Tool errors are returned to Gemini as `{"error": "..."}` rather than raised. After the limit, ask Gemini for a final answer with tools disabled.

### 7.4 Streaming
`/messages/stream`: save the user message → emit `user_message` → run the tool loop non-streamed (emit a `tool` event per call) → stream the final answer with `chat_stream` (emit `delta` events) → save the assistant message → emit `done`. On failure emit `error` and save nothing for the assistant.

### 7.5 Starter suggestions (`GET /chat/suggestions`)
Static list plus context: with a scan → "How can I make this meal healthier?", "Is this enough protein for me?"; without → "Cheap high-protein foods in a hostel?", "What should I eat at night when studying?", "How did I do today?", "Healthy options at a college canteen?". Return 4.

## 8. Mock mode (`app/services/llm/mock_client.py`)
`MOCK_AI=true` swaps in `MockGeminiClient` and `MockClassifier` via dependency injection (`app/api/deps.py`). It must:
- Return a realistic fixture for image analysis: "Rajma Chawal Plate" with 3 items (rajma 150 g, steamed rice 150 g, onion salad 50 g), plausible nutrients and 2 tips.
- Return `is_food=false` when `description` contains `"not food"` (lets tests trigger `NOT_FOOD`).
- Allow tests to queue custom responses: `mock.queue("analyze_food_image", FoodAnalysisLLM(...))`.
- Text estimate: split the description on commas/"and" and return one plausible item per part.
- Chat: if the message contains "today", issue a `get_daily_intake` function call first, then answer using the tool result. If it contains "log", call `log_meal`. Otherwise return a canned helpful answer. Streaming yields the answer in ~5 chunks.
- Classifier mock returns `[{"label": "chicken_curry", "score": 0.62}, {"label": "samosa", "score": 0.11}, {"label": "falafel", "score": 0.05}]`.

## 9. Optional: `ml/finetune_indian_food.py` (write it, do NOT run it)
A runnable script (Colab / Kaggle GPU) that:
1. Loads an ImageFolder dataset from `ml/data/indian_food/<class>/*.jpg` (e.g. the Kaggle "Indian Food Images" dataset, 80 classes), optionally merged with a Food-101 subset via `datasets.load_dataset("food101")`.
2. Starts from `nateraw/food` with `AutoModelForImageClassification.from_pretrained(..., num_labels=N, id2label, label2id, ignore_mismatched_sizes=True)`.
3. Phase 1: freeze the ViT encoder and train the head (3 epochs, lr 1e-3). Phase 2: unfreeze the last 4 encoder layers (8 epochs, lr 5e-5, cosine schedule, warmup 0.1, label smoothing 0.1). Augmentations: RandomResizedCrop 224, horizontal flip, ColorJitter.
4. Reports top-1/top-5 accuracy and saves to `ml/output/indian-food-vit/`, then prints "set CLASSIFIER_MODEL_ID=ml/output/indian-food-vit".

`ml/README.md` explains dataset download, the Colab command and how to switch the backend to the new model. The script only needs to pass `ruff` and `python -m py_compile` during the build.
