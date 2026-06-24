from __future__ import annotations

from pathlib import Path

from pydantic import Field

from .config_models import (
    _StrictBase,
    AskConfig,
    FeishuConfig,
    FirecrawlConfig,
    GraphitiConfig,
    GuardrailsConfig,
    LangExtractConfig,
    LangSmithConfig,
    KnowledgeGapConfig,
    MicrosoftGraphRagConfig,
    OpenAIConfig,
    PlannerConfig,
    PolicyConfig,
    ReflectionReplaySettings,
    ResearchConfig,
    ReviewDigestConfig,
    RouterConfig,
    ShortTermMemoryConfig,
    StructuredConfig,
    WebApiConfig,
    WebSearchConfig,
)


class Settings(_StrictBase):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    embedding_provider: str = "local"
    llm_provider: str = "stub"
    default_user: str = "default"
    postgres_url: str | None = None
    max_verify_retries: int = 1

    graphiti: GraphitiConfig = Field(default_factory=GraphitiConfig)
    ms_graphrag: MicrosoftGraphRagConfig = Field(default_factory=MicrosoftGraphRagConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    structured: StructuredConfig = Field(default_factory=StructuredConfig)
    firecrawl: FirecrawlConfig = Field(default_factory=FirecrawlConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    review_digest: ReviewDigestConfig = Field(default_factory=ReviewDigestConfig)
    knowledge_gap: KnowledgeGapConfig = Field(default_factory=KnowledgeGapConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    web: WebApiConfig = Field(default_factory=WebApiConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    langextract: LangExtractConfig = Field(default_factory=LangExtractConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    ask: AskConfig = Field(default_factory=AskConfig)
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    guardrails: GuardrailsConfig = Field(default_factory=GuardrailsConfig)
    reflection_replay: ReflectionReplaySettings = Field(default_factory=ReflectionReplaySettings)

    @classmethod
    def from_env(cls) -> "Settings":
        from .config_env import settings_from_env

        return settings_from_env(cls)
