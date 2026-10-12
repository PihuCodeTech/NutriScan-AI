"""Shared API objects: the envelope, Nutrients, pagination and enums."""

from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

MealType = Literal["breakfast", "lunch", "dinner", "snack"]
Confidence = Literal["high", "medium", "low"]
ItemSource = Literal["ai", "user_edit", "user_added"]
Sex = Literal["male", "female", "other"]
ActivityLevel = Literal["sedentary", "light", "moderate", "active", "very_active"]
Goal = Literal["lose", "maintain", "gain"]
DietType = Literal["veg", "eggetarian", "non_veg", "vegan"]
Kitchen = Literal["none", "kettle", "burner"]
HealthLabel = Literal["good", "moderate", "needs_attention"]
HealthColor = Literal["green", "amber", "red"]

MEAL_TYPES: tuple[str, ...] = ("breakfast", "lunch", "dinner", "snack")


class Envelope(BaseModel, Generic[T]):
    """Every response: `{success, code, message, data}`."""

    success: bool = True
    code: str = "OK"
    message: str = "OK"
    data: T | None = None


class ErrorEnvelope(BaseModel):
    success: bool = False
    code: str = Field(examples=["NOT_FOUND"])
    message: str = Field(examples=["Scan not found."])
    data: None = None
    details: Any = None


NUTRIENT_EXAMPLE = {
    "calories": 432.0,
    "protein_g": 15.1,
    "carbohydrates_g": 77.0,
    "fat_g": 6.5,
    "saturated_fat_g": 1.1,
    "fiber_g": 10.6,
    "sugar_g": 3.8,
    "sodium_mg": 545.0,
}


class Nutrients(BaseModel):
    """Fixed nutrient keys. Units: kcal, grams, and milligrams for sodium."""

    model_config = ConfigDict(json_schema_extra={"example": NUTRIENT_EXAMPLE})

    calories: float = Field(0, ge=0, description="kcal")
    protein_g: float = Field(0, ge=0)
    carbohydrates_g: float = Field(0, ge=0)
    fat_g: float = Field(0, ge=0)
    saturated_fat_g: float = Field(0, ge=0)
    fiber_g: float = Field(0, ge=0)
    sugar_g: float = Field(0, ge=0)
    sodium_mg: float = Field(0, ge=0)


class Page(BaseModel, Generic[T]):
    items: list[T]
    page: int
    page_size: int
    total: int


class PageParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
