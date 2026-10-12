from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolCallTrace(BaseModel):
    name: str
    args: dict[str, Any] = {}
    summary: str


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "c0ffee00-1111-4222-8333-444455556666",
                "role": "assistant",
                "content": "So far today you've had **1,250 kcal** of your 2,630 kcal target…",
                "image_url": None,
                "tool_calls": [
                    {
                        "name": "get_daily_intake",
                        "args": {"date": "2026-09-28"},
                        "summary": "Checked your intake for 2026-09-28",
                    }
                ],
                "created_at": "2026-09-28T09:30:00Z",
            }
        }
    )

    id: str
    role: Literal["user", "assistant"]
    content: str
    image_url: str | None = None
    tool_calls: list[ToolCallTrace] | None = None
    created_at: datetime


class ChatSessionCreate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    scan_id: str | None = None


class ChatSessionRename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ChatSessionOut(BaseModel):
    id: str
    title: str
    scan_id: str | None
    last_message_preview: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatSessionDetail(BaseModel):
    session: ChatSessionOut
    messages: list[ChatMessageOut]


class ChatExchange(BaseModel):
    user_message: ChatMessageOut
    assistant_message: ChatMessageOut


class Suggestions(BaseModel):
    suggestions: list[str]
