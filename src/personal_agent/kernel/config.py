from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from personal_agent.kernel.contracts.answer_result import AnswerResultConfig
from personal_agent.kernel.contracts.goal import ConversationGoalMode
from personal_agent.kernel.contracts.tool import ConversationToolProfile
from personal_agent.kernel.feature_flags import FeatureFlags, load_feature_flags

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
    SkillScopesConfig,
    StructuredConfig,
    WebApiConfig,
    WebSearchConfig,
    WorkspaceChangesConfig,
)


class Settings(_StrictBase):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    embedding_provider: str = "local"
    llm_provider: str = "stub"
    prompt_language: str = "zh"
    default_user: str = "default"
    postgres_url: str | None = None
    max_verify_retries: int = 1
    url_capture_provider: Literal["firecrawl", "builtin"] = "builtin"
    action_diagnostics_reveal_field_names: bool = False
    retrieval_experiment_config_path: Path | None = None
    bash_execution_config_path: Path | None = None
    skill_root: Path | None = None
    skill_scopes: SkillScopesConfig = Field(default_factory=SkillScopesConfig)
    answer_result: AnswerResultConfig = Field(default_factory=AnswerResultConfig)
    conversation_tools: ConversationToolProfile = Field(default_factory=ConversationToolProfile)
    conversation_goal_mode: ConversationGoalMode = ConversationGoalMode.ENABLED
    feature_flags: FeatureFlags = Field(default_factory=load_feature_flags)

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
    workspace_changes: WorkspaceChangesConfig | None = None
    enterprise_knowledge: EnterpriseKnowledgeConfig = Field(default_factory=EnterpriseKnowledgeConfig)
    ask: AskConfig = Field(default_factory=AskConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    reflection_replay: ReflectionReplaySettings = Field(default_factory=ReflectionReplaySettings)

    @model_validator(mode="after")
    def validate_skill_scope_principals(self) -> "Settings":
        configured = set(self.web.api_keys.values()) | set(self.web.admin_api_keys.values())
        if any(entry.principal not in configured for entry in (*self.skill_scopes.users, *self.skill_scopes.projects)):
            raise ValueError("用户级和工程级技能的绑定主体须配置 Web 认证密钥")
        return self

    @property
    def web_search_available(self) -> bool:
        return bool(self.web_search.api_key)

    @classmethod
    def from_env(cls) -> "Settings":
        from personal_agent.kernel.config_env import settings_from_env

        return settings_from_env(cls)
