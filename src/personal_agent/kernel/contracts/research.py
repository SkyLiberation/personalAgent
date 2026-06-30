from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


ResearchFrequency = Literal["daily", "weekdays", "weekly"]
ResearchRunStatus = Literal[
    "queued",
    "running",
    "completed_verified",
    "completed_with_limitations",
    "partial_no_supported_claims",
    "partial_budget_exhausted",
    "partial_low_yield",
    "failed",
    "skipped",
]
ResearchFeedbackAction = Literal["expand", "useful", "not_interested", "bookmark", "save"]
ResearchAction = Literal["search_web", "fetch_source", "search_personal_graph", "stop"]
ResearchDecisionStatus = Literal["planned", "executed", "skipped"]
ResearchQueryPhase = Literal["exploration", "verification"]
EvidenceGapType = Literal["missing_primary_source", "single_source", "missing_personal_context", "low_yield"]
EvidenceGapStatus = Literal["open", "resolved", "accepted"]
DigestClaimSupportLevel = Literal[
    "supported",
    "partially_supported",
    "unsupported",
    "contradicted",
]
DigestClaimImportance = Literal["core", "supporting", "context"]
ResearchType = Literal[
    "technical_product_update",
    "academic_research",
    "company_financials",
    "general_news",
]
ResearchSourceType = Literal[
    "official",
    "docs",
    "github",
    "paper",
    "filing",
    "investor_relations",
    "transcript",
    "media",
    "blog",
    "social",
    "unknown",
]
SourcePreference = ResearchSourceType
EvidenceRequirement = Literal[
    "official_or_multi_source",
    "official_required",
    "paper_or_primary_source",
    "primary_financial_source_required",
    "multi_source",
]
RankingObjective = Literal[
    "confidence_first",
    "personal_relevance_first",
    "novelty_first",
    "impact_first",
]
VerificationStrictness = Literal["low", "medium", "medium_high", "high"]
ResearchQueryIntent = Literal[
    "latest",
    "official",
    "docs",
    "repo",
    "paper",
    "technical",
    "media",
    "financial_filing",
    "transcript",
]


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
    max_exploration_queries: int = Field(default=3, ge=1, le=20)
    max_verification_queries: int = Field(default=2, ge=0, le=20)
    max_satisfaction_model_calls: int = Field(default=1, ge=0, le=10)
    max_search_results: int = Field(default=30, ge=1, le=100)
    max_fulltext_fetches: int = Field(default=5, ge=0, le=20)
    max_tool_calls: int = Field(default=15, ge=1, le=100)


class ResearchPolicy(BaseModel):
    research_type: ResearchType = "general_news"
    source_preference: list[SourcePreference] = Field(
        default_factory=lambda: ["official", "paper", "media"]
    )
    evidence_requirement: EvidenceRequirement = "official_or_multi_source"
    ranking_objective: RankingObjective = "confidence_first"
    verification_strictness: VerificationStrictness = "medium_high"


class ResearchQuery(BaseModel):
    query: str
    intent: ResearchQueryIntent = "latest"
    priority: float = Field(default=0.5, ge=0, le=1)


class ResearchDecision(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    iteration: int
    action: ResearchAction
    query: str = ""
    purpose: str = ""
    event_id: str | None = None
    gap_id: str | None = None
    reason: str = ""
    status: ResearchDecisionStatus = "planned"
    result_count: int = 0
    query_phase: ResearchQueryPhase = "exploration"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    elapsed_ms: int = 0


class EvidenceGap(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    event_id: str | None = None
    type: EvidenceGapType
    severity: float = Field(default=0.5, ge=0, le=1)
    suggested_action: str = ""
    status: EvidenceGapStatus = "open"


class ResearchSatisfaction(BaseModel):
    coverage_score: float = Field(default=0, ge=0, le=1)
    confidence_score: float = Field(default=0, ge=0, le=1)
    remaining_critical_gaps: list[EvidenceGap] = Field(default_factory=list)
    marginal_gain: float = Field(default=0, ge=0, le=1)
    should_continue: bool = True
    reason: str = ""


class ResearchStageTiming(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    stage: str
    decision_id: str | None = None
    elapsed_ms: int = 0
    item_count: int = 0
    recorded_at: datetime = Field(default_factory=utc_now)


class ResearchToolCallTrace(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    tool_name: str
    decision_id: str | None = None
    elapsed_ms: int = 0
    ok: bool = False
    result_count: int = 0
    error_kind: str = ""
    recorded_at: datetime = Field(default_factory=utc_now)


class ResearchState(BaseModel):
    run_id: str
    topic: str
    instructions: str = ""
    max_items: int = Field(default=5, ge=1, le=20)
    window_start: datetime
    window_end: datetime
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    query_history: list[str] = Field(default_factory=list)
    decisions: list[ResearchDecision] = Field(default_factory=list)
    policy: ResearchPolicy = Field(default_factory=ResearchPolicy)
    query_plan: list[ResearchQuery] = Field(default_factory=list)
    evidence_gaps: list[EvidenceGap] = Field(default_factory=list)
    iteration_count: int = 0
    exploration_query_count: int = 0
    verification_query_count: int = 0
    low_yield_rounds: int = 0
    tool_call_count: int = 0
    satisfaction_model_call_count: int = 0
    stage_timings: list[ResearchStageTiming] = Field(default_factory=list)
    tool_call_traces: list[ResearchToolCallTrace] = Field(default_factory=list)
    personal_relevance_cache: dict[str, PersonalRelevance] = Field(default_factory=dict)
    satisfaction: ResearchSatisfaction | None = None
    stop_reason: str = ""


class ResearchSource(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    decision_id: str | None = None
    query: str = ""
    query_phase: ResearchQueryPhase = "exploration"
    url: str
    canonical_url: str
    domain: str
    title: str
    snippet: str = ""
    published_at: datetime | None = None
    source_type: ResearchSourceType = "unknown"
    provider: str = ""
    content: str = ""
    content_fingerprint: str = ""


class PersonalRelevance(BaseModel):
    score: float = Field(default=0, ge=0, le=1)
    related_note_ids: list[str] = Field(default_factory=list)
    relation: Literal[
        "not_relevant",
        "weak_match",
        "background_context",
        "related_update",
        "direct_update",
        "support",
        "conflict",
    ] = "not_relevant"
    explanation: str = ""


class EventScoreBreakdown(BaseModel):
    source_quality: float = Field(default=0, ge=0, le=1)
    evidence_support: float = Field(default=0, ge=0, le=1)
    source_independence: float = Field(default=0, ge=0, le=1)
    novelty: float = Field(default=0, ge=0, le=1)
    impact: float = Field(default=0, ge=0, le=1)
    personal_relevance: float = Field(default=0, ge=0, le=1)
    uncertainty_penalty: float = Field(default=0, ge=0, le=1)
    final_score: float = Field(default=0, ge=0, le=1)


class ResearchEventFrameSnapshot(BaseModel):
    source_url: str = ""
    title: str = ""
    actor: str = ""
    action: str = ""
    object: str = ""
    event_type: str = "news"
    occurred_at: str | None = None
    entities: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)


class ResearchEvent(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    canonical_key: str
    title: str
    summary: str
    occurred_at: datetime | None = None
    entities: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    event_type: str = "news"
    source_ids: list[str] = Field(default_factory=list)
    frame: ResearchEventFrameSnapshot | None = None
    sources: list[ResearchSource] = Field(default_factory=list)
    importance_score: float = Field(default=0.5, ge=0, le=1)
    novelty_score: float = Field(default=0.5, ge=0, le=1)
    confidence_score: float = Field(default=0.3, ge=0, le=1)
    personal_relevance: PersonalRelevance = Field(default_factory=PersonalRelevance)
    status: Literal["verified", "reported", "uncertain", "conflicted"] = "uncertain"
    final_score: float = 0
    score_breakdown: EventScoreBreakdown = Field(default_factory=EventScoreBreakdown)


class DigestClaim(BaseModel):
    text: str
    event_id: str | None = None
    claim_importance: DigestClaimImportance = "core"
    source_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    evidence_spans: list[str] = Field(default_factory=list)
    support_level: DigestClaimSupportLevel = "unsupported"


class IntelligenceDigestItem(BaseModel):
    short_id: str
    event_id: str
    title: str
    what_happened: str
    why_it_matters: str
    personal_relevance: str = ""
    confidence_label: str
    source_urls: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    decision_ids: list[str] = Field(default_factory=list)
    claims: list[DigestClaim] = Field(default_factory=list)


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
    max_items: int = Field(default=5, ge=1, le=20)
    window_start: datetime
    window_end: datetime
    policy: ResearchPolicy = Field(default_factory=ResearchPolicy)
    query_plan: list[str] = Field(default_factory=list)
    query_plan_details: list[ResearchQuery] = Field(default_factory=list)
    source_count: int = 0
    event_count: int = 0
    selected_count: int = 0
    digest_id: str | None = None
    budget: ResearchBudget = Field(default_factory=ResearchBudget)
    research_state: ResearchState | None = None
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
            max_items=subscription.max_items,
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

