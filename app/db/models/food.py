"""Reference nutrition table. Gemini estimates what's on the plate and how many grams; the server computes
nutrients from these per-100 g values (IFCT 2017 / USDA), falling back to Gemini's estimate when a food is
not in the table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk


class Food(UUIDPk, Timestamps, Base):
    __tablename__ = "foods"

    canonical_name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    per_100g: Mapped[dict[str, Any]] = mapped_column(JSON)  # the fixed nutrient keys, per 100 g edible
    serving_g: Mapped[float] = mapped_column(Float)  # a typical single-serving weight
    serving_name: Mapped[str] = mapped_column(String(60), default="serving")
    source: Mapped[str] = mapped_column(String(40), default="IFCT 2017")  # provenance, shown to users
    region: Mapped[str] = mapped_column(String(8), default="IN")

    aliases: Mapped[list[FoodAlias]] = relationship(
        back_populates="food", lazy="selectin", cascade="all, delete-orphan"
    )


class FoodAlias(UUIDPk, Base):
    __tablename__ = "food_aliases"

    alias: Mapped[str] = mapped_column(String(120), unique=True, index=True)  # canonicalized synonym
    food_id: Mapped[str] = mapped_column(String(36), ForeignKey("foods.id", ondelete="CASCADE"), index=True)

    food: Mapped[Food] = relationship(back_populates="aliases")
