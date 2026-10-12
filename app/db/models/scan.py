from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, Timestamps, UUIDPk


class Scan(UUIDPk, Timestamps, Base):
    __tablename__ = "scans"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(12))
    image_path: Mapped[str] = mapped_column(String(255))
    image_sha256: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    meal_type: Mapped[str] = mapped_column(String(12))  # for history/grouping (user choice or time-of-day guess)
    meal_type_explicit: Mapped[bool] = mapped_column(default=False)  # did the user pick it? drives neutral scoring
    meal_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    classifier_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    classifier_predictions: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    ai_model: Mapped[str] = mapped_column(String(100), default="")
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    health: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw_ai_response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    logged_intake_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("intake_entries.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
    )

    items: Mapped[list[ScanItem]] = relationship(
        back_populates="scan",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ScanItem.position",
    )


class ScanItem(UUIDPk, Base):
    __tablename__ = "scan_items"

    scan_id: Mapped[str] = mapped_column(String(36), ForeignKey("scans.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    name: Mapped[str] = mapped_column(String(120))
    canonical_name: Mapped[str] = mapped_column(String(120))
    quantity_g: Mapped[float] = mapped_column(Float)
    serving_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    confidence: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(12), default="ai")  # ai | user_edit | user_added
    nutrition_source: Mapped[str] = mapped_column(String(12), default="estimate")  # table | estimate
    nutrients: Mapped[dict[str, Any]] = mapped_column(JSON)
    nutrients_per_100g: Mapped[dict[str, Any]] = mapped_column(JSON)

    scan: Mapped[Scan] = relationship(back_populates="items")
