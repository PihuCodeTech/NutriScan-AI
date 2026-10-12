from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, utcnow

if TYPE_CHECKING:
    from app.db.models.user import User


class Profile(Base):
    __tablename__ = "profiles"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String(10), nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    activity_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    goal: Mapped[str | None] = mapped_column(String(10), nullable=True)
    diet_type: Mapped[str | None] = mapped_column(String(15), nullable=True)
    allergies: Mapped[list[Any]] = mapped_column(JSON, default=list)
    conditions: Mapped[list[Any]] = mapped_column(JSON, default=list)
    country: Mapped[str] = mapped_column(String(2), default="IN")
    kitchen: Mapped[str] = mapped_column(String(12), default="burner")  # none | kettle | burner
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    user: Mapped[User] = relationship(back_populates="profile")

    @property
    def onboarding_complete(self) -> bool:
        return all(
            v is not None for v in (self.age, self.sex, self.height_cm, self.weight_kg, self.activity_level, self.goal)
        )
