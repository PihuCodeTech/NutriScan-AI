"""Deterministic `LLMClient` for MOCK_AI=true (tests and frontend development). No network."""

from __future__ import annotations

import re
from collections import Counter, defaultdict, deque
from collections.abc import AsyncIterator
from typing import Any

from app.services.llm.schemas import (
    ChatHistoryItem,
    ChatTurn,
    FoodAnalysisLLM,
    FunctionCall,
    InsightLLM,
    LLMFoodItem,
    LLMNutrients,
    LLMRecipe,
    RecipesLLM,
    StreamChunk,
    TipsLLM,
    ToolSpec,
)

MOCK_MODEL = "mock-gemini"


def _n(cal: float, p: float, c: float, f: float, sat: float, fib: float, sug: float, na: float) -> LLMNutrients:
    return LLMNutrients(
        calories=cal,
        protein_g=p,
        carbohydrates_g=c,
        fat_g=f,
        saturated_fat_g=sat,
        fiber_g=fib,
        sugar_g=sug,
        sodium_mg=na,
    )


def rajma_chawal_fixture() -> FoodAnalysisLLM:
    """The canonical image-analysis fixture: 'Rajma Chawal Plate' with 3 items."""
    return FoodAnalysisLLM(
        is_food=True,
        meal_name="Rajma Chawal Plate",
        items=[
            LLMFoodItem(
                name="Rajma",
                canonical_name="kidney_bean_curry",
                quantity_g=150,
                serving_description="1 katori (~150 g)",
                confidence="high",
                nutrients=_n(215, 10.5, 30, 6, 1.0, 9.0, 1.5, 480),
            ),
            LLMFoodItem(
                name="Steamed Rice",
                canonical_name="steamed_rice",
                quantity_g=150,
                serving_description="1 cup cooked (~150 g)",
                confidence="high",
                nutrients=_n(195, 4.0, 42, 0.4, 0.1, 0.6, 0.1, 5),
            ),
            LLMFoodItem(
                name="Onion Salad",
                canonical_name="onion_salad",
                quantity_g=50,
                serving_description="small side (~50 g)",
                confidence="medium",
                nutrients=_n(22, 0.6, 5, 0.1, 0.0, 1.0, 2.2, 60),
            ),
        ],
        tips=[
            "Add a bowl of curd or some roasted chana for extra protein.",
            "Great fibre from the rajma — keep the salad and go easy on extra salt.",
        ],
    )


# key: (aliases, typical grams per unit, per-100 g nutrients: kcal, P, C, F, sat, fibre, sugar, sodium)
_FOODS: dict[str, tuple[tuple[str, ...], float, tuple[float, ...]]] = {
    "roti": (("roti", "chapati", "chapathi", "phulka"), 40, (264, 8.5, 46, 5.3, 1.0, 6.5, 1.5, 350)),
    "dal": (("dal", "daal", "dhal", "sambar"), 150, (110, 6, 14, 3.4, 0.6, 3.5, 1.0, 280)),
    "rice": (("rice", "chawal", "pulao"), 150, (130, 2.7, 28.5, 0.3, 0.1, 0.4, 0.1, 2)),
    "rajma": (("rajma",), 150, (144, 7, 20, 4, 0.7, 6, 1, 320)),
    "lassi": (("lassi",), 250, (90, 3.1, 13, 2.9, 1.8, 0, 12, 45)),
    "curd": (("curd", "dahi", "yogurt", "raita"), 100, (61, 3.5, 4.7, 3.3, 2.1, 0, 4.7, 46)),
    "egg": (("egg", "eggs", "anda", "omelette"), 50, (143, 12.6, 0.7, 9.5, 3.1, 0, 0.4, 142)),
    "paneer": (("paneer",), 100, (270, 18, 3.6, 20.8, 13, 0, 2.6, 30)),
    "chicken": (("chicken",), 150, (150, 14, 4, 9, 2.5, 0.8, 1.5, 420)),
    "poha": (("poha",), 150, (180, 3.3, 30, 5.5, 0.8, 1.5, 1.5, 300)),
    "idli": (("idli",), 40, (118, 3.9, 25, 0.4, 0.1, 1.2, 0.3, 330)),
    "dosa": (("dosa",), 100, (177, 4, 29, 5, 1, 1.5, 0.5, 390)),
    "samosa": (("samosa",), 60, (301, 5, 32, 17, 4, 2.5, 1.5, 420)),
    "noodles": (("maggi", "noodles", "ramen"), 250, (140, 3.5, 19, 5.5, 2.5, 0.8, 0.8, 480)),
    "banana": (("banana",), 120, (96, 1.1, 22.8, 0.3, 0.1, 2.6, 12.2, 1)),
    "salad": (("salad", "cucumber", "onion"), 75, (25, 1, 5, 0.2, 0, 1.8, 2.5, 20)),
    "chai": (("chai", "tea"), 150, (48, 1.5, 7, 1.6, 1, 0, 6, 20)),
    "sprouts": (("sprouts", "chana", "chickpea"), 100, (130, 8, 20, 2, 0.3, 6, 2, 150)),
}
_GENERIC = (150.0, (154.0, 5.0, 20.0, 6.0, 1.5, 2.0, 3.0, 250.0))
_WORD_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "half": 0.5}


def _estimate_part(part: str) -> LLMFoodItem:
    text = part.strip().lower()
    key, unit_g, per100 = None, _GENERIC[0], _GENERIC[1]
    for k, (aliases, g, values) in _FOODS.items():
        if any(re.search(rf"\b{re.escape(a)}\b", text) for a in aliases):
            key, unit_g, per100 = k, g, values
            break

    grams_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams?)\b", text)
    count_match = re.match(r"^(\d+(?:\.\d+)?|a|an|one|two|three|four|half)\b", text)
    if grams_match:
        grams = float(grams_match.group(1))
        serving = f"{grams:g} g"
    elif count_match:
        token = count_match.group(1)
        count = float(_WORD_NUMBERS.get(token, token)) if token in _WORD_NUMBERS else float(token)
        grams = unit_g * count
        serving = f"{count:g} serving(s) (~{grams:g} g)"
    else:
        grams = unit_g
        serving = f"1 typical serving (assumed, ~{grams:g} g)"

    cleaned = re.sub(r"(\d+(?:\.\d+)?)\s*(?:g|gm|gms|grams?)\b", "", text)
    cleaned = re.sub(r"^(\d+(?:\.\d+)?|a|an|one|two|three|four|half)\b", "", cleaned)
    cleaned = re.sub(r"\b(of|glass|katori|bowl|plate|cup|pieces?|small|medium|large)\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .") or (key or "food")
    name = cleaned.title() if key is None else (key.title() if len(cleaned) > 30 else cleaned.title())

    f = grams / 100.0
    kcal, p, c, fat, sat, fib, sug, na = (v * f for v in per100)
    return LLMFoodItem(
        name=name,
        canonical_name=re.sub(r"[^a-z0-9]+", "_", (key or cleaned).lower()).strip("_") or "food_item",
        quantity_g=round(grams, 1),
        serving_description=serving,
        confidence="high" if key else "low",
        nutrients=_n(
            round(kcal), round(p, 1), round(c, 1), round(fat, 1), round(sat, 1), round(fib, 1), round(sug, 1), round(na)
        ),
    )


def _split_description(text: str) -> list[str]:
    parts = re.split(r",|\band\b|\bwith\b|\+|&", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p and p.strip()]


_MEAL_WORDS = ("breakfast", "lunch", "dinner", "snack")


class MockGeminiClient:
    """Fixture-driven fake. Tests may queue responses: `mock.queue("analyze_food_image", FoodAnalysisLLM(...))`
    (an Exception instance is raised instead of returned)."""

    def __init__(self) -> None:
        self._queues: dict[str, deque[Any]] = defaultdict(deque)
        self.calls: Counter[str] = Counter()
        self.last_kwargs: dict[str, dict[str, Any]] = {}
        self._last_model = MOCK_MODEL

    @property
    def last_model_used(self) -> str:
        return self._last_model

    def queue(self, method: str, response: Any) -> None:
        self._queues[method].append(response)

    def reset(self) -> None:
        self._queues.clear()
        self.calls.clear()
        self.last_kwargs.clear()

    def _record(self, method: str, **kwargs: Any) -> Any:
        self.calls[method] += 1
        self.last_kwargs[method] = kwargs
        if self._queues[method]:
            item = self._queues[method].popleft()
            if isinstance(item, BaseException):
                raise item
            return item
        return None

    # ------------------------------------------------------------ structured

    async def analyze_food_image(
        self, image: bytes, mime: str, *, hints: list[dict[str, Any]], user_ctx: str, description: str | None
    ) -> FoodAnalysisLLM:
        queued = self._record("analyze_food_image", hints=hints, user_ctx=user_ctx, description=description)
        if queued is not None:
            return queued
        if description and "not food" in description.lower():
            return FoodAnalysisLLM(is_food=False, rejection_reason="The image does not appear to contain food.")
        return rajma_chawal_fixture()

    async def estimate_from_text(self, text: str, *, user_ctx: str) -> FoodAnalysisLLM:
        queued = self._record("estimate_from_text", text=text, user_ctx=user_ctx)
        if queued is not None:
            return queued
        if "not food" in text.lower():
            return FoodAnalysisLLM(is_food=False, rejection_reason="That doesn't sound like food.")
        parts = _split_description(text) or [text]
        items = [_estimate_part(p) for p in parts[:10]]
        name = " & ".join(i.name for i in items[:3])
        return FoodAnalysisLLM(
            is_food=True,
            meal_name=name[:60] or "Meal",
            items=items,
            tips=["Add a katori of curd or sprouts for protein.", "Include a fruit or salad for fibre."],
        )

    async def generate_tips(
        self, *, items: list[dict[str, Any]], totals: dict[str, Any], flags: list[dict[str, Any]], user_ctx: str
    ) -> TipsLLM:
        queued = self._record("generate_tips", items=items, totals=totals, flags=flags, user_ctx=user_ctx)
        if queued is not None:
            return queued
        tips = []
        nutrients = {f.get("nutrient") for f in flags}
        if "sodium_mg" in nutrients:
            tips.append("Skip the extra pickle and papad to cut down on salt.")
        if "protein_g" in nutrients:
            tips.append("Add a katori of dal, curd or sprouts for more protein.")
        tips.append("Add a small salad or a fruit for fibre and freshness.")
        if len(tips) < 2:
            tips.append("Drink a glass of water with your meal.")
        return TipsLLM(tips=tips[:3])

    async def daily_insight(self, *, day_summary: dict[str, Any], user_ctx: str) -> InsightLLM:
        queued = self._record("daily_insight", day_summary=day_summary, user_ctx=user_ctx)
        if queued is not None:
            return queued
        pct = day_summary.get("percent_of_target", {}).get("calories", 0)
        if not day_summary.get("entries"):  # an empty day gets no praise for logging
            return InsightLLM(
                headline="Ready when you are",
                summary="Nothing logged yet today. Scan your first plate to see how it fits your day.",
                tips=[
                    "A mess thali with dal and curd is a solid, cheap start.",
                    "Keep roasted chana or a banana handy for the evening hunger.",
                    "Keep a water bottle at your desk and sip through the day.",
                ],
            )
        return InsightLLM(
            headline="Nice work logging today!" if pct <= 110 else "A big day so far",
            summary=f"You're at about {pct}% of your calorie target so far. "
            "Keep meals balanced with protein and fibre.",
            tips=[
                "Add curd, dal or paneer to your next meal for protein.",
                "Snack on fruit or roasted chana instead of chips.",
                "Keep a water bottle at your desk and sip through the day.",
            ],
        )

    async def suggest_recipes(
        self, *, ingredients: list[str], kitchen: str, count: int, user_ctx: str, note: str | None
    ) -> RecipesLLM:
        queued = self._record(
            "suggest_recipes", ingredients=ingredients, kitchen=kitchen, count=count, user_ctx=user_ctx, note=note
        )
        if queued is not None:
            return queued
        main = ingredients[0] if ingredients else "oats"
        styles = [("bowl", 12), ("chaat", 10), ("wrap", 15), ("stir-fry", 20), ("salad", 8)]
        recipes = [
            LLMRecipe(
                name=f"{main.title()} {style}",
                why=f"Uses your {main} with a protein boost and little oil.",
                time_minutes=minutes,
                kitchen="none" if kitchen == "none" else ("kettle" if kitchen == "kettle" else "burner"),
                ingredients=[*ingredients[:4], "curd", "lemon", "salt"],
                steps=[f"Prepare the {main}.", "Mix in the other ingredients.", "Season with lemon and salt."],
                nutrients=_n(380 + 20 * k, 16, 52, 11, 2.5, 6, 5, 420),
            )
            for k, (style, minutes) in enumerate(styles[:count])
        ]
        return RecipesLLM(recipes=recipes)

    # ------------------------------------------------------------ chat

    @staticmethod
    def _decide(history: list[ChatHistoryItem]) -> ChatTurn:
        last_user_idx = max((i for i, h in enumerate(history) if h.role == "user"), default=-1)
        if last_user_idx < 0:
            return ChatTurn(text="Hi! Ask me anything about food and nutrition.")
        user = history[last_user_idx]
        text = (user.text or "").lower()
        results = [r for h in history[last_user_idx + 1 :] if h.role == "tool" for r in h.function_results]
        called = {r.name for r in results}

        if re.search(r"\blog\b", text) and "log_meal" not in called:
            meal_type = next((m for m in _MEAL_WORDS if m in text), "snack")
            desc = re.sub(r"\blog\b", "", text)
            desc = re.sub(rf"\b(for|as|to my|to)\s+(my\s+)?({'|'.join(_MEAL_WORDS)})\b", "", desc)
            desc = re.sub(r"\s+", " ", desc).strip(" .,!?") or "meal"
            return ChatTurn(
                text=None,
                function_calls=[
                    FunctionCall(name="log_meal", args={"description": desc, "meal_type": meal_type}, id="mock-1")
                ],
            )
        if "today" in text and "get_daily_intake" not in called and "log_meal" not in called:
            return ChatTurn(text=None, function_calls=[FunctionCall(name="get_daily_intake", args={}, id="mock-2")])

        if results:
            r = results[-1]
            resp = r.response.get("result", r.response)
            if isinstance(resp, dict) and "error" in resp:
                return ChatTurn(text=f"Sorry, I couldn't do that: {resp['error']}")
            if r.name == "log_meal":
                entry = resp.get("entry", {})
                kcal = entry.get("totals", {}).get("calories", 0)
                return ChatTurn(
                    text=f"Done! I've logged **{entry.get('name', 'your meal')}** (~{kcal:.0f} kcal) to your "
                    f"{entry.get('meal_type', 'meals')}. Anything else?"
                )
            if r.name == "get_daily_intake":
                totals = resp.get("totals", {})
                targets = resp.get("targets", {})
                return ChatTurn(
                    text=f"So far today you've had about **{totals.get('calories', 0):.0f} kcal** of your "
                    f"{targets.get('calories', 0):.0f} kcal target, with {totals.get('protein_g', 0):.0f} g protein.\n"
                    "- Add curd, dal or paneer for protein\n- Keep dinner light and balanced"
                )
            return ChatTurn(text="Here's what I found — let me know if you'd like more detail!")

        if user.image:
            return ChatTurn(
                text="Nice plate! It looks like a home-style Indian meal — roughly 450–550 kcal with moderate "
                "protein. Want me to log it?"
            )
        return ChatTurn(
            text="Here are some cheap, hostel-friendly ideas:\n"
            "- **Protein:** paneer, curd, dal, sprouts, roasted chana\n"
            "- **Fibre:** fruit, salad, whole-wheat roti\n- **Hydration:** keep a water bottle handy\n"
            "Want ideas tailored to your mess menu?"
        )

    async def chat_turn(self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec]) -> ChatTurn:
        queued = self._record("chat_turn", system=system, history=history, tools=tools)
        if queued is not None:
            return queued
        turn = self._decide(history)
        if not tools and turn.function_calls:
            return ChatTurn(text="Here's my best answer without looking anything else up: keep meals balanced!")
        return turn

    async def chat_stream(
        self, *, system: str, history: list[ChatHistoryItem], tools: list[ToolSpec] | None = None
    ) -> AsyncIterator[StreamChunk]:
        queued = self._record("chat_stream", system=system, history=history, tools=tools)
        turn = queued if queued is not None else self._decide(history)
        if not tools and turn.function_calls:
            turn = ChatTurn(text="Here's my best answer without looking anything else up: keep meals balanced!")
        if turn.text:
            size = max(1, -(-len(turn.text) // 5))  # ~5 chunks
            for i in range(0, len(turn.text), size):
                yield StreamChunk(text=turn.text[i : i + size])
        yield StreamChunk(final=turn)
