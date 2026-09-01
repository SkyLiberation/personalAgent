from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field

from personal_agent.kernel.config_models import (
    _StrictBase,
    AskConfig,
    EnterpriseKnowledgeConfig,
    FeishuConfig,
    FirecrawlConfig,
    GraphitiConfig,
    GPTResearcherA2AConfig,
    LangExtractConfig,
    LangSmithConfig,
    KnowledgeGapConfig,
    InteractionLoopConfig,
    MCPConfig,
    OpenAIConfig,
    PolicyConfig,
    ReflectionReplaySettings,
    ResearchConfig,
    ReviewDigestConfig,
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
    url_capture_provider: Literal["firecrawl", "builtin"] = "builtin"
    action_diagnostics_reveal_field_names: bool = False

    graphiti: GraphitiConfig = Field(default_factory=GraphitiConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    structured: StructuredConfig = Field(default_factory=StructuredConfig)
    firecrawl: FirecrawlConfig = Field(default_factory=FirecrawlConfig)
    gpt_researcher_a2a: GPTResearcherA2AConfig = Field(default_factory=GPTResearcherA2AConfig)
    interaction_loop: InteractionLoopConfig = Field(default_factory=InteractionLoopConfig)
    web_search: WebSearchConfig = Field(default_factory=WebSearchConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    review_digest: ReviewDigestConfig = Field(default_factory=ReviewDigestConfig)
    knowledge_gap: KnowledgeGapConfig = Field(default_factory=KnowledgeGapConfig)
    research: ResearchConfig = Field(default_factory=ResearchConfig)
    web: WebApiConfig = Field(default_factory=WebApiConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    langextract: LangExtractConfig = Field(default_factory=LangExtractConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    enterprise_knowledge: EnterpriseKnowledgeConfig = Field(default_factory=EnterpriseKnowledgeConfig)
    ask: AskConfig = Field(default_factory=AskConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    reflection_replay: ReflectionReplaySettings = Field(default_factory=ReflectionReplaySettings)

    @property
    def web_search_available(self) -> bool:
        return bool(self.web_search.api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        from personal_agent.kernel.config_env import settings_from_env

        return settings_from_env(cls)
