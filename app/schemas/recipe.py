"""Gemini meal ideas from the ingredients a student has."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import Nutrients

Kitchen = Literal["none", "kettle", "burner"]


class RecipeSuggestIn(BaseModel):
    ingredients: list[str] = Field(min_length=1, max_length=20, examples=[["poha", "onion", "peanuts"]])
    kitchen: Kitchen = Field("burner", description="Equipment available: none, kettle only, or a burner")
    count: int = Field(3, ge=1, le=5, description="How many meal ideas to return")
    note: str | None = Field(None, max_length=200, examples=["high protein, under 15 minutes"])

    @field_validator("ingredients")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        items = [i.strip()[:40] for i in v if i and i.strip()]
        if not items:
            raise ValueError("add at least one ingredient")
        return list(dict.fromkeys(items))  # de-duplicate, keep order


class RecipeOut(BaseModel):
    name: str
    why: str
    time_minutes: int
    kitchen: Kitchen
    ingredients: list[str]
    steps: list[str]
    nutrients: Nutrients = Field(description="Per serving, sanitised by the server")


class RecipeSuggestOut(BaseModel):
    meals: list[RecipeOut]
    ai_model: str
    disclaimer: str
