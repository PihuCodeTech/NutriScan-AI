from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, UUIDPk


class InsightCache(UUIDPk, CreatedAt, Base):
    __tablename__ = "insight_cache"
    __table_args__ = (UniqueConstraint("user_id", "date", "totals_hash", name="uq_insight_cache_user_date_hash"),)

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    date: Mapped[date] = mapped_column(Date)
    totals_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
