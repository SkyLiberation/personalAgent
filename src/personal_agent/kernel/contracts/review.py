from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from personal_agent.kernel.models import KnowledgeNote, ReviewCard, local_now

ReviewFeedbackOutcome = Literal["remembered", "forgotten", "later"]


class ReviewDigestSection(BaseModel):
    """Structured section inside a review digest."""

    title: str
    items: list[str] = Field(default_factory=list)


class ReviewDigest(BaseModel):
    """Structured review digest before channel-specific formatting."""

    user_id: str
    generated_at: datetime = Field(default_factory=local_now)
    recent_notes: list[KnowledgeNote] = Field(default_factory=list)
    due_cards: list[ReviewCard] = Field(default_factory=list)
    sections: list[ReviewDigestSection] = Field(default_factory=list)
    empty_reason: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.recent_notes and not self.due_cards


class DigestSubscription(BaseModel):
    """A configured target for review digest delivery."""

    id: str
    user_id: str
    channel: str = "feishu"
    target_type: str = "chat_id"
    target_id: str
    schedule_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    enabled: bool = True


class DeliveryTarget(BaseModel):
    channel: str
    target_type: str
    target_id: str


class DeliveryMessage(BaseModel):
    title: str = ""
    text: str
    metadata: dict[str, str] = Field(default_factory=dict)


class DeliveryResult(BaseModel):
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


class ReviewDigestJobResult(BaseModel):
    subscription_id: str
    user_id: str
    channel: str
    target_id: str
    delivered: bool
    skipped: bool = False
    delivery_id: str | None = None
    idempotency_key: str | None = None
    error: str | None = None


class ReviewFeedbackResult(BaseModel):
    ok: bool
    short_id: str
    outcome: ReviewFeedbackOutcome
    review_card_id: str | None = None
    delivery_id: str | None = None
    message: str = ""
    error: str | None = None
