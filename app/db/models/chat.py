from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, CreatedAt, Timestamps, UUIDPk


class ChatSession(UUIDPk, Timestamps, Base):
    __tablename__ = "chat_sessions"

    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    scan_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("scans.id", ondelete="SET NULL"), nullable=True)


class ChatMessage(UUIDPk, CreatedAt, Base):
    __tablename__ = "chat_messages"

    session_id: Mapped[str] = mapped_column(String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))
    content: Mapped[str] = mapped_column(Text, default="")
    image_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tool_calls: Mapped[list[Any] | None] = mapped_column(JSON, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
