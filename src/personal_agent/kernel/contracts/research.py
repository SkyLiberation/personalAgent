from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


ResearchFrequency = Literal["daily", "weekdays", "weekly"]
ResearchRunStatus = Literal["queued", "running", "completed", "partial", "failed", "skipped"]
ResearchFeedbackAction = Literal["expand", "useful", "not_interested", "bookmark", "save"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class SchedulePolicy(BaseModel):
    frequency: ResearchFrequency = "daily"
    schedule_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    weekdays: list[int] = Field(default_factory=lambda: [0])

    @field_validator("schedule_time")
    @classmethod
    def validate_time(cls, value: str) -> str:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("schedule_time must be HH:MM")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("schedule_time must be HH:MM")
        return f"{hour:02d}:{minute:02d}"


class SourcePreferences(BaseModel):
    preferred_domains: list[str] = Field(default_factory=list)
    excluded_domains: list[str] = Field(default_factory=list)
    prefer_primary_sources: bool = True
    require_multiple_sources: bool = True


class ContentPreferences(BaseModel):
    include_topics: list[str] = Field(default_factory=list)
    exclude_topics: list[str] = Field(default_factory=list)
    minimum_importance: float = Field(default=0.25, ge=0, le=1)
    novelty_weight: float = Field(default=0.3, ge=0, le=1)
    personal_relevance_weight: float = Field(default=0.3, ge=0, le=1)
    empty_policy: Literal["send_short", "silent"] = "send_short"


class DeliveryTarget(BaseModel):
    channel: str = "feishu"
    target_type: str = "chat_id"
    target_id: str = ""


class ResearchSubscription(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: str = "default"
    name: str
    topic: str
    instructions: str = ""
    seed_queries: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    region: str | None = None
    lookback_hours: int = Field(default=24, ge=1, le=24 * 30)
    max_items: int = Field(default=5, ge=1, le=20)
    source_preferences: SourcePreferences = Field(default_factory=SourcePreferences)
    content_preferences: ContentPreferences = Field(default_factory=ContentPreferences)
    schedule: SchedulePolicy = Field(default_factory=SchedulePolicy)
    delivery: DeliveryTarget = Field(default_factory=DeliveryTarget)
    save_policy: Literal["none", "digest_only", "approved_items"] = "approved_items"
    enabled: bool = True
    last_window_end: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ResearchBudget(BaseModel):
    max_queries: int = Field(default=5, ge=1, le=20)
    max_search_results: int = Field(default=30, ge=1, le=100)
    max_fulltext_fetches: int = Field(default=5, ge=0, le=20)
    max_tool_calls: int = Field(default=15, ge=1, le=100)


class ResearchSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    url: str
    canonical_url: str
    domain: str
    title: str
    snippet: str = ""
    published_at: datetime | None = None
    source_type: Literal["official", "paper", "media", "blog", "social", "unknown"] = "unknown"
    provider: str = ""
    content: str = ""
    content_fingerprint: str = ""


class PersonalRelevance(BaseModel):
    score: float = Field(default=0, ge=0, le=1)
    related_note_ids: list[str] = Field(default_factory=list)
    relation: Literal["new", "update", "support", "conflict", "background"] = "new"
    explanation: str = ""


class ResearchEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    canonical_key: str
    title: str
    summary: str
    occurred_at: datetime | None = None
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    event_type: str = "news"
    sources: list[ResearchSource] = Field(default_factory=list)
    importance_score: float = Field(default=0.5, ge=0, le=1)
    novelty_score: float = Field(default=0.5, ge=0, le=1)
    confidence_score: float = Field(default=0.3, ge=0, le=1)
    personal_relevance: PersonalRelevance = Field(default_factory=PersonalRelevance)
    status: Literal["verified", "reported", "uncertain", "conflicted"] = "uncertain"
    final_score: float = 0


class IntelligenceDigestItem(BaseModel):
    short_id: str
    event_id: str
    title: str
    what_happened: str
    why_it_matters: str
    personal_relevance: str = ""
    confidence_label: str
    source_urls: list[str] = Field(default_factory=list)


class IntelligenceDigest(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str
    user_id: str
    title: str
    executive_summary: str
    items: list[IntelligenceDigestItem] = Field(default_factory=list)
    no_major_update: bool = False
    generated_at: datetime = Field(default_factory=utc_now)

    def to_text(self) -> str:
        lines = [self.title, "", self.executive_summary]
        for item in self.items:
            lines.extend([
                "",
                f"{item.short_id}. {item.title}",
                f"发生了什么：{item.what_happened}",
                f"为什么重要：{item.why_it_matters}",
                f"与你的知识关联：{item.personal_relevance or '暂无直接关联'}",
                f"可信度：{item.confidence_label}",
                "来源：" + "、".join(item.source_urls[:3]),
                f"操作：回复 {item.short_id} 展开 / 有用 / 不感兴趣 / 收藏 / 入库",
            ])
        return "\n".join(lines)


class ResearchRun(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    subscription_id: str | None = None
    user_id: str
    trigger_type: Literal["manual", "scheduled", "event"] = "manual"
    status: ResearchRunStatus = "queued"
    topic: str
    instructions: str = ""
    window_start: datetime
    window_end: datetime
    query_plan: list[str] = Field(default_factory=list)
    source_count: int = 0
    event_count: int = 0
    selected_count: int = 0
    digest_id: str | None = None
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    failure_reason: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    @classmethod
    def for_subscription(
        cls,
        subscription: ResearchSubscription,
        *,
        window_end: datetime,
        trigger_type: Literal["manual", "scheduled"] = "scheduled",
        budget: ResearchBudget | None = None,
    ) -> "ResearchRun":
        start = subscription.last_window_end or (
            window_end - timedelta(hours=subscription.lookback_hours)
        )
        return cls(
            subscription_id=subscription.id,
            user_id=subscription.user_id,
            trigger_type=trigger_type,
            topic=subscription.topic,
            instructions=subscription.instructions,
            window_start=start,
            window_end=window_end,
            budget=budget or ResearchBudget(),
        )


class ResearchFeedback(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    user_id: str
    subscription_id: str | None = None
    run_id: str
    event_id: str | None = None
    action: ResearchFeedbackAction
    source_channel: str = "web"
    source_message_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

