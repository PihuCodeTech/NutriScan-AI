"""All prompt templates (docs/05_AI_PIPELINE.md §4)."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_FOOD_ANALYST = """\
You are a precise nutrition analyst for an app used by college students in hostels and shared flats,
mostly in India. You estimate what is on a plate and its nutrition from photos or descriptions.
Be realistic about Indian mess, canteen, street-food and home-style portions and cooking (oil, ghee, salt).
Return only data that matches the requested JSON schema."""

SYSTEM_COACH = """\
You are a friendly, practical nutrition coach for college students living in hostels or on their own,
mostly in India. Be encouraging and budget-aware (hostel mess, canteen, street food, instant noodles;
cheap swaps like curd, dal, sprouts, eggs, fruit). Never shame the user. No medical diagnosis or
prescriptions; never suggest crash diets, skipping meals or eating below a safe minimum.
Respect the user's diet type and allergies strictly. Return only data matching the JSON schema."""

JSON_REPAIR_SUFFIX = "\n\nReturn ONLY valid JSON matching the schema. No markdown, no commentary."

_ITEM_RULES = """\
2. Identify EVERY distinct food/drink item (a thali may have 5–8 items: rice, roti, dal, sabzi,
   curd, salad, pickle, sweet). One entry per item. Do not merge distinct items.
3. For each item estimate the edible quantity in grams{visual}.
   Typical references: 1 roti ≈ 40 g, 1 katori dal/sabzi ≈ 150 g, 1 cup cooked rice ≈ 150 g,
   1 idli ≈ 40 g, 1 dosa ≈ 100 g, 1 samosa ≈ 60 g, 1 packet instant noodles (cooked) ≈ 250 g.
4. Give nutrients for the ESTIMATED QUANTITY (not per 100 g). Prefer values consistent with
   IFCT 2017 / Indian Nutrient Databank for Indian foods and USDA FoodData Central otherwise.
   Account for cooking oil/ghee typical of the preparation.
   Keep calories consistent with Atwater factors (protein 4, carbs 4, fat 9 kcal/g).
5. Use the common local name in the user's country for "name" (e.g. "Rajma", "Poha", "Chole"), and a
   lowercase snake_case English "canonical_name".
6. Set confidence per item: high (clearly visible/clearly described, common dish), medium, low
   (occluded/ambiguous).
7. meal_name: a short friendly name for the whole plate (e.g. "Mess Lunch Thali").
8. tips: 2–3 short, practical, budget-friendly suggestions for a student about THIS meal
   (what to add, reduce or swap). Respect diet_type and allergies. No medical claims. ≤ 25 words each."""

_VISUAL_CUES = (
    " from visual cues: plate/katori/glass size, item\n   height and spread, count of pieces. "
    "Don't mistake a zoomed-in container for a large one"
)


def format_hints(hints: list[dict[str, Any]] | None) -> str:
    if not hints:
        return "none"
    return ", ".join(f"{h['label']} ({float(h['score']):.2f})" for h in hints)


def food_image_prompt(*, user_ctx: str, hints: list[dict[str, Any]] | None, description: str | None) -> str:
    return f"""\
USER CONTEXT:
{user_ctx}

IMAGE CLASSIFIER HINTS (a Food-101 model; it knows mostly Western dishes, so treat these as weak hints only):
{format_hints(hints)}

USER DESCRIPTION: {description.strip() if description and description.strip() else "none"}

TASK:
1. Decide if the image shows food or drink meant for eating. If not, set is_food=false, give a short
   rejection_reason, and leave items empty.
{_ITEM_RULES.format(visual=_VISUAL_CUES)}"""


def text_estimate_prompt(*, text: str, user_ctx: str) -> str:
    return f"""\
USER CONTEXT:
{user_ctx}

MEAL DESCRIPTION: {text.strip()}

TASK:
1. Set is_food=true unless the text clearly isn't food or drink (then is_food=false, a short
   rejection_reason, and empty items). If quantities are missing, assume typical single servings
   and say so in serving_description (e.g. "1 katori (assumed)").
{_ITEM_RULES.format(visual=" from the description")}"""


def tips_prompt(
    *, items: list[dict[str, Any]], totals: dict[str, Any], flags: list[dict[str, Any]], user_ctx: str
) -> str:
    item_lines = "\n".join(f"- {i.get('name')}: {i.get('quantity_g')} g" for i in items) or "- (no items)"
    flag_lines = (
        "\n".join(
            f"- {f.get('message')} ({f.get('nutrient')}: {f.get('value')} vs meal target {f.get('meal_target')})"
            for f in flags
        )
        or "- none"
    )
    return f"""\
USER CONTEXT:
{user_ctx}

MEAL ITEMS:
{item_lines}

MEAL TOTALS: {json.dumps(totals)}

HEALTH FLAGS FROM THE APP (address these first):
{flag_lines}

TASK: Write 2–3 short, practical, budget-friendly tips (≤ 25 words each) for a student about THIS
meal: what to add, reduce or swap. Address the flags first. Respect diet_type and allergies.
No medical claims."""


def daily_insight_prompt(*, day_summary: dict[str, Any], user_ctx: str) -> str:
    return f"""\
USER CONTEXT:
{user_ctx}

TODAY'S DATA (computed by the app; do not recompute):
{json.dumps(day_summary, indent=1, default=str)}

TASK: Write a daily insight.
- headline: ≤ 8 words, encouraging.
- summary: exactly 2 sentences about how the day is going versus the targets (health_status is
  decided by the app: on_track / over / under / no_data).
- tips: exactly 3 short, practical tips for the rest of today or tomorrow (hostel/budget friendly).
Never shame the user. If there is no data, gently encourage logging meals."""


_KITCHEN_TEXT = {
    "none": "no cooking at all (no kettle, no stove): only assembling, soaking or ready-to-eat items",
    "kettle": "only an electric kettle (hot water): no stove, no microwave",
    "burner": "an induction plate or gas burner with one pan",
}


def recipe_prompt(*, ingredients: list[str], kitchen: str, count: int, user_ctx: str, note: str | None) -> str:
    return f"""\
USER CONTEXT:
{user_ctx}

INGREDIENTS THE STUDENT HAS: {", ".join(ingredients)}
KITCHEN: {_KITCHEN_TEXT.get(kitchen, kitchen)}
EXTRA REQUEST: {note or "none"}

TASK: Suggest {count} different, realistic meals this student can make in a hostel room or shared flat.
- Use mainly the listed ingredients. You may add cheap staples (salt, spices, oil, lemon, onion, curd, bread,
  eggs only if the diet allows) and must list every ingredient used.
- Respect the kitchen limit strictly, the diet type and every allergy. Never include an allergen.
- Prefer healthier choices: more protein and fibre, less oil, salt and sugar than typical street food.
- name: short dish name. why: one line on why it's a good choice for them.
- time_minutes: realistic total time. kitchen: the least equipment the recipe really needs.
- steps: 3–6 short imperative steps.
- nutrients: for ONE serving, consistent with Atwater factors (protein 4, carbs 4, fat 9 kcal/g)."""


CHAT_SYSTEM_TEMPLATE = """\
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
{linked_scan_block}
Current local time: {local_time}"""
