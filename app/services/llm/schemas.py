"""Schemas for LLM I/O: Pydantic models used as Gemini `response_schema`, plus
provider-neutral chat types shared by the real and mock clients."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

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
    tips: list[str] = []  # 2–3 short tips


class TipsLLM(BaseModel):
    tips: list[str]


class InsightLLM(BaseModel):
    headline: str
    summary: str
    tips: list[str]


class LLMRecipe(BaseModel):
    name: str
    why: str  # one line: why it's a good pick for this student
    time_minutes: int
    kitchen: Literal["none", "kettle", "burner"]  # least equipment needed
    ingredients: list[str]
    steps: list[str]
    nutrients: LLMNutrients  # per serving


class RecipesLLM(BaseModel):
    recipes: list[LLMRecipe]


# ---------------------------------------------------------------- chat types


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema (type: object)


@dataclass
class FunctionCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class FunctionResult:
    name: str
    response: dict[str, Any]
    id: str | None = None


@dataclass
class ChatHistoryItem:
    """One turn of conversation, provider-neutral.

    role "user": text and/or image. role "model": text and/or function calls (`raw` keeps the
    provider-native content, e.g. to replay Gemini thought signatures). role "tool": function results.
    """

    role: Literal["user", "model", "tool"]
    text: str | None = None
    image: bytes | None = None
    image_mime: str | None = None
    function_calls: list[FunctionCall] = field(default_factory=list)
    function_results: list[FunctionResult] = field(default_factory=list)
    raw: Any = None


@dataclass
class ChatTurn:
    text: str | None
    function_calls: list[FunctionCall] = field(default_factory=list)
    raw: Any = None


@dataclass
class StreamChunk:
    """A streamed text delta, or (last) the complete turn once the stream ends."""

    text: str | None = None
    final: ChatTurn | None = None
