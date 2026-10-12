from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config import DISCLAIMER
from app.schemas.common import (
    NUTRIENT_EXAMPLE,
    Confidence,
    HealthColor,
    HealthLabel,
    ItemSource,
    MealType,
    Nutrients,
)


class FoodItem(BaseModel):
    id: str
    name: str
    canonical_name: str
    quantity_g: float
    serving_description: str | None = None
    confidence: Confidence
    source: ItemSource
    nutrition_source: Literal["table", "estimate"] = "estimate"  # "table" = looked up in the foods table
    nutrients: Nutrients


class HealthFlag(BaseModel):
    nutrient: str
    level: Literal["high", "low"]
    value: float
    meal_target: float
    message: str


class Health(BaseModel):
    score: int = Field(ge=0, le=100)
    label: HealthLabel
    color: HealthColor
    flags: list[HealthFlag] = []
    tips: list[str] = []
    disclaimer: str = DISCLAIMER


class ClassifierPrediction(BaseModel):
    label: str
    display_name: str
    score: float


class ClassifierInfo(BaseModel):
    model: str
    predictions: list[ClassifierPrediction]


SCAN_RESULT_EXAMPLE = {
    "id": "6f1c2d5e-3a4b-4c8d-9e0f-1a2b3c4d5e6f",
    "status": "completed",
    "image_url": "http://localhost:8000/media/2026/09/0b7e3c2a-5d1f-4e8a-9c3b-2f6d7e8a9b0c.jpg",
    "meal_name": "Rajma Chawal Plate",
    "meal_type": "lunch",
    "description": "hostel lunch",
    "classifier": {
        "model": "nateraw/food",
        "predictions": [
            {"label": "chicken_curry", "display_name": "Chicken Curry", "score": 0.62},
            {"label": "samosa", "display_name": "Samosa", "score": 0.11},
            {"label": "falafel", "display_name": "Falafel", "score": 0.05},
        ],
    },
    "items": [
        {
            "id": "1d2c3b4a-0000-4000-8000-000000000001",
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
                "sodium_mg": 480.0,
            },
        }
    ],
    "totals": NUTRIENT_EXAMPLE,
    "health": {
        "score": 93,
        "label": "good",
        "color": "green",
        "flags": [],
        "tips": [
            "Add a bowl of curd or a boiled egg for extra protein.",
            "Great fibre from the rajma — keep the salad!",
        ],
        "disclaimer": DISCLAIMER,
    },
    "ai_model": "gemini-3.8-flash",
    "logged_intake_id": None,
    "created_at": "2026-09-28T07:30:00Z",
}


class ScanResult(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": SCAN_RESULT_EXAMPLE})

    id: str
    status: Literal["completed", "rejected"]
    image_url: str
    meal_name: str | None
    meal_type: MealType
    description: str | None
    classifier: ClassifierInfo | None
    items: list[FoodItem]
    totals: Nutrients
    health: Health | None
    ai_model: str
    logged_intake_id: str | None
    created_at: datetime


class ScanTotalsSummary(BaseModel):
    calories: float


class ScanHealthSummary(BaseModel):
    score: int
    label: HealthLabel
    color: HealthColor


class ScanSummary(BaseModel):
    id: str
    status: Literal["completed", "rejected"]
    image_url: str
    meal_name: str | None
    meal_type: MealType
    totals: ScanTotalsSummary
    health: ScanHealthSummary | None
    created_at: datetime


class ItemEdit(BaseModel):
    """One edit. With `id`: change grams, rename, or `remove`. Without `id`: add a new item."""

    id: str | None = None
    name: str | None = Field(None, min_length=1, max_length=120)
    quantity_g: float | None = Field(None, gt=0, le=5000)
    remove: bool = False

    @model_validator(mode="after")
    def _check(self) -> ItemEdit:
        if self.id is None:
            if self.remove:
                raise ValueError("remove requires an item id")
            if not self.name:
                raise ValueError("new items need a name")
        elif not self.remove and self.name is None and self.quantity_g is None:
            raise ValueError("nothing to change: give quantity_g, name or remove")
        return self


class ScanItemsPatch(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {"id": "1d2c3b4a-0000-4000-8000-000000000001", "quantity_g": 120},
                    {"id": "1d2c3b4a-0000-4000-8000-000000000002", "name": "Jeera Rice"},
                    {"id": "1d2c3b4a-0000-4000-8000-000000000003", "remove": True},
                    {"name": "Curd", "quantity_g": 100},
                ]
            }
        }
    )

    items: list[ItemEdit] = Field(min_length=1, max_length=20)


class ScanLogIn(BaseModel):
    meal_type: MealType | None = None
    eaten_at: datetime | None = None
    is_street_food: bool = False
