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

    profile: Mapped[Profile] = relationship(
        back_populates="user", uselist=False, lazy="selectin", cascade="all, delete-orphan"
    )
