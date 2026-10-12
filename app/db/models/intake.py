from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UTCDateTime, UUIDPk


class IntakeEntry(UUIDPk, CreatedAt, Base):
    __tablename__ = "intake_entries"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(12))
    scan_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(120))
    meal_type: Mapped[str] = mapped_column(String(12))
    eaten_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    local_date: Mapped[date] = mapped_column(Date, index=True)
    items: Mapped[list[Any]] = mapped_column(JSON, default=list)
    totals: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_street_food: Mapped[bool] = mapped_column(default=False)
    is_home_cooked: Mapped[bool] = mapped_column(default=False)
