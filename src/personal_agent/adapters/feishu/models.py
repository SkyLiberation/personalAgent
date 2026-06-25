from __future__ import annotations

from pydantic import BaseModel, Field


class FeishuIncomingMessage(BaseModel):
    event_id: str | None = None
    event_type: str | None = None
    chat_id: str | None = None
    open_id: str | None = None
    user_id: str = "default"
    session_id: str = "default"
    message_id: str | None = None
    message_type: str = "text"
    text: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
