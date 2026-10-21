from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreatedAt, UUIDPk

if TYPE_CHECKING:
    from app.db.models.profile import Profile


class User(UUIDPk, CreatedAt, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(100))

    # Joined, not selectin: the user is loaded on every authenticated request, and a second query costs a full
    # round trip to the database (~400 ms to a far-away Supabase region).
    profile: Mapped[Profile] = relationship(
        back_populates="user", uselist=False, lazy="joined", cascade="all, delete-orphan"
    )
