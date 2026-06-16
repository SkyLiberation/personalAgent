from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GraphitiConfig(_StrictBase):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "password"
    group_prefix: str = "personal-agent"

    search_strategy: str = "hybrid_rrf"
    search_max_hops: int = 2
    search_limit: int = 10
    search_citation_limit: int = 20
    search_min_score: float = 0.0

    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_small_model: str | None = None

    sync_max_attempts: int = 3
    sync_max_workers: int = 4
    sync_max_notes_per_capture: int = 12
    sync_initial_backoff_seconds: float = 2.0
    sync_backoff_multiplier: float = 2.0
    sync_max_backoff_seconds: float = 20.0

    add_episode_timeout_seconds: float = 900.0
    search_timeout_seconds: float = 45.0
    episode_max_chars: int = 8000
    content_filter_fallback: bool = True


class MicrosoftGraphRagConfig(_StrictBase):
    enabled: bool = False
    root: Path = Path("./data/ms_graphrag")
    executable: str = "graphrag"
    completion_model_provider: str = "openai"
    completion_model: str | None = None
    completion_api_key: str | None = None
    completion_api_base: str | None = None
    embedding_model_provider: str = "openai"
    embedding_model: str | None = None
    embedding_api_key: str | None = None
    embedding_api_base: str | None = None
    query_method: str = "local"
    index_method: str = "standard"
    response_type: str = "Multiple Paragraphs"
    auto_index: bool = False
    command_timeout_seconds: float = 600.0


class OpenAIConfig(_StrictBase):
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4.1-mini"
    small_model: str = "deepseek-v4-flash"
    embedding_model: str = "text-embedding-3-small"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None


class RouterConfig(_StrictBase):
    """Dedicated LLM config for the intent router (``agent/router.py``).

    The router uses OpenAI-style strict ``json_schema`` structured outputs, so
    it needs an endpoint that supports them (e.g. gpt-5.4-mini). This is kept
    separate from ``OpenAIConfig`` (which may point at an endpoint without
    json_schema support, such as DeepSeek) so the router can target a
    compatible model without disturbing the other LLM paths.

    ``model`` is exposed as ``small_model`` too, because ``traced_chat_completion``
    falls back to ``config.small_model`` when no explicit model is passed.
    """

    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-5.4-mini"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    extra_body: dict[str, Any] = Field(default_factory=dict)
    # Structured-output mode: "json_schema" (strict) or "json_object" (valid JSON only).
    structured_output: str = "json_schema"

    @property
    def small_model(self) -> str:
        return self.model


class StructuredConfig(RouterConfig):
    """Dedicated LLM config for structured-output orchestration steps.

    Used by ``_structured_llm_respond`` in
    ``agent/orchestration_nodes/_helpers.py`` (e.g. the ``solidify_draft`` step),
    which emits OpenAI-style strict ``json_schema`` outputs. Same shape/rationale
    as :class:`RouterConfig`: keep it separate from ``OpenAIConfig`` (DeepSeek,
    no json_schema support) so structured steps can target a compatible model
    without disturbing the ask/answer paths. Defaults fall back to ``ROUTER_*``
    then ``OPENAI_*`` when ``STRUCTURED_*`` is unset.
    """


class FirecrawlConfig(_StrictBase):
    api_key: str | None = None
    base_url: str = "https://api.firecrawl.dev"
    timeout_ms: int = 60000


class WebSearchConfig(_StrictBase):
    provider: str = "tavily"
    api_key: str | None = None
    base_url: str | None = None
    timeout_ms: int = 60000
    # 外部访问来源白名单（域名后缀）。空表示不限制。
    allowed_domains: tuple[str, ...] = ()


class FeishuConfig(_StrictBase):
    enabled: bool = False
    app_id: str | None = None
    app_secret: str | None = None
    base_url: str = "https://open.feishu.cn"
    use_default_user: bool = True


class ReviewDigestConfig(_StrictBase):
    enabled: bool = False
    user_id: str = "default"
    feishu_chat_ids: tuple[str, ...] = ()
    schedule_time: str = "09:00"
    timezone: str = "Asia/Shanghai"
    scheduler_enabled: bool = False
    scheduler_tick_seconds: int = 60


class WebApiConfig(_StrictBase):
    api_keys: dict[str, str] = Field(default_factory=dict)
    # API keys granted admin scope: cross-user audit queries and un-redacted payloads.
    admin_api_keys: dict[str, str] = Field(default_factory=dict)
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class LangSmithConfig(_StrictBase):
    enabled: bool = False
    api_key: str | None = None
    endpoint: str = "https://api.smith.langchain.com"
    project: str = "personal-agent-dev"
    workspace_id: str | None = None
    upload_inputs: bool = False
    sample_rate: float = 1.0


class LangExtractConfig(_StrictBase):
    """LangExtract layer config.

    Decoupled from OpenAIConfig (DeepSeek) and GraphitiConfig (Kimi) so the
    extraction layer can target a model that supports OpenAI-style structured
    outputs (e.g. qwen3-coder-flash) without disturbing the other LLM paths.

    This config drives only the optional LangExtract pre-extraction layer
    (``extract/``), which is currently dormant in the production capture/ask
    paths. Ask-time query understanding has its own ``PlannerConfig`` and no
    longer reuses this config.
    """

    api_key: str | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_id: str = "qwen3-coder-flash"
    max_char_buffer: int = 6000
    extraction_passes: int = 1
    max_workers: int = 4
    min_doc_chars: int = 200
    fallback_on_error: bool = True


class PlannerConfig(_StrictBase):
    """Structured-output LLM config for ask-time query understanding and rerank.

    This is the model used by ``agent/query_planner.py`` (query understanding /
    retrieval plan) and the optional LLM listwise reranker
    (``core/rerankers.py``). It is independent from the capture-time
    ``LangExtractConfig`` on purpose: query planning is an ask-side concern and
    has nothing to do with the (currently dormant) LangExtract pre-extraction
    layer. It only needs an endpoint that supports OpenAI-style strict
    ``json_schema`` outputs (e.g. ``qwen3-coder-flash``).

    If ``api_key`` is missing, the query planner falls back to a default plan +
    heuristic filters, and the LLM reranker falls back to the heuristic ranker.
    """

    api_key: str | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_id: str = "qwen3-coder-flash"
    timeout_seconds: float = 15.0


class AskConfig(_StrictBase):
    graph_provider: str = "graphiti"
    reranker: str = "heuristic"
    candidate_enricher: str = "parent_child"
    parent_child_top_n: int = 3
    parent_child_min_overlap: int = 2
    neighbor_chunk_window: int = 0
    graph_note_evidence_mode: str = "all"
    graph_note_evidence_min_overlap: int = 2
    context_max_items: int = 12
    context_char_budget: int = 5000
    llm_rerank_top_n: int = 20
    llm_rerank_timeout_seconds: float = 20.0
    llm_rerank_model: str | None = None


class ShortTermMemoryConfig(_StrictBase):
    """短期记忆（thread 对话）进 prompt 前的统一裁剪策略。"""

    max_messages: int = 12              # 进 prompt 的对话最大消息数
    token_budget: int = 1500            # 对话上下文总 token 预算
    per_message_char_limit: int = 1200  # 单条消息截断阈值（字符）
    char_budget: int = 800              # planner 等纯文本场景的字符预算
    rolling_summary_enabled: bool = True
    rolling_summary_trigger: int = 20   # 累计消息数达到此值才触发溢出滚动摘要
    tokenizer_enabled: bool = True      # 优先使用 tiktoken，缺失时回退到字符启发式
    tokenizer_encoding: str = "cl100k_base"
    cjk_chars_per_token: float = 1.5
    latin_chars_per_token: float = 4.0


class PolicyConfig(_StrictBase):
    """Programmable allow/deny overrides for the unified policy engine.

    Empty tuples mean "defer to the code-internal default rules" (current
    behavior). Populate these to pin authorization per user / source / tool /
    scope without changing code.
    """

    deny_users: tuple[str, ...] = ()
    allow_users: tuple[str, ...] = ()
    deny_sources: tuple[str, ...] = ()
    allow_sources: tuple[str, ...] = ()
    deny_tools: tuple[str, ...] = ()
    deny_scopes: tuple[str, ...] = ()
    require_confirmation_for_high_risk: bool = True


class ReflectionReplaySettings(_StrictBase):
    """跨 run 反思回注闭环（Reflexion）的开关与把关参数。

    失败/取消的 run 会生成 reflection candidate；开启后这些反思会在 replan
    与 ask 两条链路被回注，并按 run 结果做 confidence 升降与 candidate→confirmed
    晋升。关闭则回到「只存不用」行为。
    """

    enabled: bool = True
    max_items: int = 3              # 每次回注最多注入的反思条数
    min_confidence: float = 0.3     # 低于此置信度的反思不再回注
    promote_step: float = 0.2       # 命中后 run 成功，confidence 增量
    demote_step: float = 0.25       # 命中后 run 失败，confidence 减量
    promote_threshold: float = 0.8  # confidence 达到此值升为 confirmed
    reject_floor: float = 0.2       # confidence 触及此值标记 rejected


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
    web: WebApiConfig = Field(default_factory=WebApiConfig)
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)
    langextract: LangExtractConfig = Field(default_factory=LangExtractConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    ask: AskConfig = Field(default_factory=AskConfig)
    short_term: ShortTermMemoryConfig = Field(default_factory=ShortTermMemoryConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)
    reflection_replay: ReflectionReplaySettings = Field(default_factory=ReflectionReplaySettings)

    @classmethod
    def from_env(cls) -> "Settings":
        import os

        load_dotenv(override=True)
        return cls(
            data_dir=Path(os.getenv("PERSONAL_AGENT_DATA_DIR", "./data")),
            log_level=os.getenv("PERSONAL_AGENT_LOG_LEVEL", "INFO"),
            embedding_provider=os.getenv("PERSONAL_AGENT_EMBEDDING_PROVIDER", "local"),
            llm_provider=os.getenv("PERSONAL_AGENT_LLM_PROVIDER", "stub"),
            default_user=os.getenv("PERSONAL_AGENT_DEFAULT_USER", "default"),
            postgres_url=os.getenv("PERSONAL_AGENT_POSTGRES_URL"),
            max_verify_retries=int(os.getenv("AGENT_MAX_VERIFY_RETRIES", "1")),
            graphiti=GraphitiConfig(
                uri=os.getenv("PERSONAL_AGENT_GRAPHITI_URI", "bolt://localhost:7687"),
                user=os.getenv("PERSONAL_AGENT_GRAPHITI_USER", "neo4j"),
                password=os.getenv("PERSONAL_AGENT_GRAPHITI_PASSWORD", "password"),
                group_prefix=os.getenv(
                    "PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX", "personal-agent"
                ),
                search_strategy=os.getenv(
                    "PERSONAL_AGENT_GRAPH_SEARCH_STRATEGY", "hybrid_rrf"
                ),
                search_max_hops=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SEARCH_MAX_HOPS", "2")
                ),
                search_limit=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SEARCH_LIMIT", "10")
                ),
                search_citation_limit=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SEARCH_CITATION_LIMIT", "20")
                ),
                search_min_score=float(
                    os.getenv("PERSONAL_AGENT_GRAPH_SEARCH_MIN_SCORE", "0.0")
                ),
                llm_api_key=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_API_KEY"),
                llm_base_url=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL"),
                llm_model=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_MODEL"),
                llm_small_model=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL"),
                sync_max_attempts=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_ATTEMPTS", "3")
                ),
                sync_max_workers=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_WORKERS", "4")
                ),
                sync_max_notes_per_capture=int(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_NOTES_PER_CAPTURE", "12")
                ),
                sync_initial_backoff_seconds=float(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_INITIAL_BACKOFF_SECONDS", "2.0")
                ),
                sync_backoff_multiplier=float(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_BACKOFF_MULTIPLIER", "2.0")
                ),
                sync_max_backoff_seconds=float(
                    os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_BACKOFF_SECONDS", "20.0")
                ),
                add_episode_timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_GRAPHITI_ADD_EPISODE_TIMEOUT_SECONDS", "900")
                ),
                search_timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_GRAPHITI_SEARCH_TIMEOUT_SECONDS", "45")
                ),
                episode_max_chars=int(
                    os.getenv("PERSONAL_AGENT_GRAPHITI_EPISODE_MAX_CHARS", "8000")
                ),
                content_filter_fallback=_as_bool(
                    os.getenv("PERSONAL_AGENT_GRAPHITI_CONTENT_FILTER_FALLBACK", "true")
                ),
            ),
            ms_graphrag=MicrosoftGraphRagConfig(
                enabled=_as_bool(os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_ENABLED", "false")),
                root=Path(os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_ROOT", "./data/ms_graphrag")),
                executable=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_EXECUTABLE", "graphrag"),
                completion_model_provider=os.getenv(
                    "PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_MODEL_PROVIDER", "openai"
                ),
                completion_model=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_MODEL"),
                completion_api_key=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_KEY"),
                completion_api_base=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_BASE"),
                embedding_model_provider=os.getenv(
                    "PERSONAL_AGENT_MS_GRAPHRAG_EMBEDDING_MODEL_PROVIDER", "openai"
                ),
                embedding_model=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_EMBEDDING_MODEL"),
                embedding_api_key=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_EMBEDDING_API_KEY"),
                embedding_api_base=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_EMBEDDING_API_BASE"),
                query_method=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_QUERY_METHOD", "local"),
                index_method=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_INDEX_METHOD", "standard"),
                response_type=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_RESPONSE_TYPE", "Multiple Paragraphs"),
                auto_index=_as_bool(os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_AUTO_INDEX", "false")),
                command_timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMMAND_TIMEOUT_SECONDS", "600")
                ),
            ),
            openai=OpenAIConfig(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                small_model=os.getenv("OPENAI_SMALL_MODEL", "deepseek-v4-flash"),
                embedding_model=os.getenv(
                    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
                ),
                timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS", "30")
                ),
                max_retries=int(os.getenv("PERSONAL_AGENT_OPENAI_MAX_RETRIES", "2")),
                embedding_api_key=os.getenv("EMBEDDING_API_KEY"),
                embedding_base_url=os.getenv("EMBEDDING_BASE_URL"),
            ),
            router=RouterConfig(
                api_key=os.getenv("ROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("ROUTER_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("ROUTER_MODEL", "gpt-5.4-mini"),
                timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_ROUTER_TIMEOUT_SECONDS", "30")
                ),
                max_retries=int(os.getenv("PERSONAL_AGENT_ROUTER_MAX_RETRIES", "2")),
                extra_body=_parse_json_env("ROUTER_EXTRA_BODY"),
                structured_output=os.getenv("ROUTER_STRUCTURED_OUTPUT", "json_schema"),
            ),
            structured=StructuredConfig(
                api_key=os.getenv("STRUCTURED_API_KEY")
                or os.getenv("ROUTER_API_KEY")
                or os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("STRUCTURED_BASE_URL")
                or os.getenv("ROUTER_BASE_URL")
                or os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("STRUCTURED_MODEL")
                or os.getenv("ROUTER_MODEL", "gpt-5.4-mini"),
                timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS", "30")
                ),
                max_retries=int(
                    os.getenv("PERSONAL_AGENT_STRUCTURED_MAX_RETRIES", "2")
                ),
                extra_body=_parse_json_env("STRUCTURED_EXTRA_BODY")
                or _parse_json_env("ROUTER_EXTRA_BODY"),
                structured_output=os.getenv("STRUCTURED_STRUCTURED_OUTPUT")
                or os.getenv("ROUTER_STRUCTURED_OUTPUT", "json_schema"),
            ),
            firecrawl=FirecrawlConfig(
                api_key=os.getenv("FIRECRAWL_API_KEY"),
                base_url=os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"),
                timeout_ms=int(os.getenv("FIRECRAWL_TIMEOUT_MS", "60000")),
            ),
            web_search=WebSearchConfig(
                provider=os.getenv("PERSONAL_AGENT_WEB_SEARCH_PROVIDER", "tavily"),
                api_key=os.getenv("PERSONAL_AGENT_WEB_SEARCH_API_KEY"),
                base_url=os.getenv("PERSONAL_AGENT_WEB_SEARCH_BASE_URL"),
                timeout_ms=int(
                    os.getenv("PERSONAL_AGENT_WEB_SEARCH_TIMEOUT_MS", "60000")
                ),
                allowed_domains=tuple(
                    d.strip()
                    for d in os.getenv("PERSONAL_AGENT_WEB_SEARCH_ALLOWED_DOMAINS", "").split(",")
                    if d.strip()
                ),
            ),
            feishu=FeishuConfig(
                enabled=_as_bool(os.getenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")),
                app_id=os.getenv("FEISHU_APP_ID"),
                app_secret=os.getenv("FEISHU_APP_SECRET"),
                base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn"),
                use_default_user=_as_bool(
                    os.getenv("PERSONAL_AGENT_FEISHU_USE_DEFAULT_USER", "true")
                ),
            ),
            review_digest=ReviewDigestConfig(
                enabled=_as_bool(os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_ENABLED", "false")),
                user_id=os.getenv(
                    "PERSONAL_AGENT_REVIEW_DIGEST_USER_ID",
                    os.getenv("PERSONAL_AGENT_DEFAULT_USER", "default"),
                ),
                feishu_chat_ids=_parse_csv(
                    os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_FEISHU_CHAT_IDS", "")
                ),
                schedule_time=os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_TIME", "09:00"),
                timezone=os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_TIMEZONE", "Asia/Shanghai"),
                scheduler_enabled=_as_bool(
                    os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_ENABLED", "false")
                ),
                scheduler_tick_seconds=int(
                    os.getenv("PERSONAL_AGENT_REVIEW_DIGEST_SCHEDULER_TICK_SECONDS", "60")
                ),
            ),
            web=WebApiConfig(
                api_keys=_parse_api_keys(os.getenv("PERSONAL_AGENT_API_KEYS", "")),
                admin_api_keys=_parse_api_keys(os.getenv("PERSONAL_AGENT_ADMIN_API_KEYS", "")),
                rate_limit_requests=int(
                    os.getenv("PERSONAL_AGENT_RATE_LIMIT_REQUESTS", "60")
                ),
                rate_limit_window_seconds=int(
                    os.getenv("PERSONAL_AGENT_RATE_LIMIT_WINDOW_SECONDS", "60")
                ),
                cors_origins=_parse_cors_origins(
                    os.getenv("PERSONAL_AGENT_CORS_ORIGINS", "http://localhost:3000")
                ),
            ),
            langsmith=LangSmithConfig(
                enabled=_as_bool(os.getenv("PERSONAL_AGENT_LANGSMITH_ENABLED", "false")),
                api_key=os.getenv("LANGSMITH_API_KEY"),
                endpoint=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
                project=os.getenv(
                    "PERSONAL_AGENT_LANGSMITH_PROJECT",
                    os.getenv("LANGSMITH_PROJECT", "personal-agent-dev"),
                ),
                workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID"),
                upload_inputs=_as_bool(
                    os.getenv("PERSONAL_AGENT_TRACE_UPLOAD_INPUTS", "false")
                ),
                sample_rate=float(os.getenv("PERSONAL_AGENT_TRACE_SAMPLE_RATE", "1.0")),
            ),
            langextract=LangExtractConfig(
                api_key=os.getenv("PERSONAL_AGENT_EXTRACT_API_KEY")
                or os.getenv("EMBEDDING_API_KEY"),
                base_url=os.getenv(
                    "PERSONAL_AGENT_EXTRACT_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
                model_id=os.getenv(
                    "PERSONAL_AGENT_EXTRACT_MODEL", "qwen3-coder-flash"
                ),
                max_char_buffer=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MAX_CHAR_BUFFER", "6000")
                ),
                extraction_passes=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_PASSES", "1")
                ),
                max_workers=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MAX_WORKERS", "4")
                ),
                min_doc_chars=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MIN_DOC_CHARS", "200")
                ),
                fallback_on_error=_as_bool(
                    os.getenv("PERSONAL_AGENT_EXTRACT_FALLBACK_ON_ERROR", "true")
                ),
            ),
            planner=PlannerConfig(
                api_key=os.getenv("PERSONAL_AGENT_PLANNER_API_KEY"),
                base_url=os.getenv(
                    "PERSONAL_AGENT_PLANNER_BASE_URL",
                    "https://dashscope.aliyuncs.com/compatible-mode/v1",
                ),
                model_id=os.getenv(
                    "PERSONAL_AGENT_PLANNER_MODEL", "qwen3-coder-flash"
                ),
                timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_PLANNER_TIMEOUT_SECONDS", "15.0")
                ),
            ),
            ask=AskConfig(
                graph_provider=os.getenv("PERSONAL_AGENT_ASK_GRAPH_PROVIDER", "graphiti"),
                reranker=os.getenv("PERSONAL_AGENT_ASK_RERANKER", "heuristic"),
                candidate_enricher=os.getenv(
                    "PERSONAL_AGENT_ASK_CANDIDATE_ENRICHER", "parent_child"
                ),
                parent_child_top_n=int(
                    os.getenv("PERSONAL_AGENT_ASK_PARENT_CHILD_TOP_N", "3")
                ),
                parent_child_min_overlap=int(
                    os.getenv("PERSONAL_AGENT_ASK_PARENT_CHILD_MIN_OVERLAP", "2")
                ),
                neighbor_chunk_window=int(
                    os.getenv("PERSONAL_AGENT_ASK_NEIGHBOR_CHUNK_WINDOW", "0")
                ),
                graph_note_evidence_mode=os.getenv(
                    "PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MODE", "all"
                ),
                graph_note_evidence_min_overlap=int(
                    os.getenv("PERSONAL_AGENT_ASK_GRAPH_NOTE_EVIDENCE_MIN_OVERLAP", "2")
                ),
                context_max_items=int(
                    os.getenv("PERSONAL_AGENT_ASK_CONTEXT_MAX_ITEMS", "12")
                ),
                context_char_budget=int(
                    os.getenv("PERSONAL_AGENT_ASK_CONTEXT_CHAR_BUDGET", "5000")
                ),
                llm_rerank_top_n=int(
                    os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_TOP_N", "20")
                ),
                llm_rerank_timeout_seconds=float(
                    os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_TIMEOUT_SECONDS", "20")
                ),
                llm_rerank_model=os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_MODEL"),
            ),
            short_term=ShortTermMemoryConfig(
                max_messages=int(
                    os.getenv("PERSONAL_AGENT_STM_MAX_MESSAGES", "12")
                ),
                token_budget=int(
                    os.getenv("PERSONAL_AGENT_STM_TOKEN_BUDGET", "1500")
                ),
                per_message_char_limit=int(
                    os.getenv("PERSONAL_AGENT_STM_PER_MESSAGE_CHAR_LIMIT", "1200")
                ),
                char_budget=int(
                    os.getenv("PERSONAL_AGENT_STM_CHAR_BUDGET", "800")
                ),
                rolling_summary_enabled=_as_bool(
                    os.getenv("PERSONAL_AGENT_STM_ROLLING_SUMMARY_ENABLED", "true")
                ),
                rolling_summary_trigger=int(
                    os.getenv("PERSONAL_AGENT_STM_ROLLING_SUMMARY_TRIGGER", "20")
                ),
                tokenizer_enabled=_as_bool(
                    os.getenv("PERSONAL_AGENT_STM_TOKENIZER_ENABLED", "true")
                ),
                tokenizer_encoding=os.getenv(
                    "PERSONAL_AGENT_STM_TOKENIZER_ENCODING", "cl100k_base"
                ),
                cjk_chars_per_token=float(
                    os.getenv("PERSONAL_AGENT_STM_CJK_CHARS_PER_TOKEN", "1.5")
                ),
                latin_chars_per_token=float(
                    os.getenv("PERSONAL_AGENT_STM_LATIN_CHARS_PER_TOKEN", "4.0")
                ),
            ),
            policy=PolicyConfig(
                deny_users=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_DENY_USERS", "")),
                allow_users=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_ALLOW_USERS", "")),
                deny_sources=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_DENY_SOURCES", "")),
                allow_sources=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_ALLOW_SOURCES", "")),
                deny_tools=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_DENY_TOOLS", "")),
                deny_scopes=_parse_csv(os.getenv("PERSONAL_AGENT_POLICY_DENY_SCOPES", "")),
                require_confirmation_for_high_risk=_as_bool(
                    os.getenv("PERSONAL_AGENT_POLICY_CONFIRM_HIGH_RISK", "true")
                ),
            ),
            reflection_replay=ReflectionReplaySettings(
                enabled=_as_bool(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_ENABLED", "true")
                ),
                max_items=int(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_MAX_ITEMS", "3")
                ),
                min_confidence=float(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_MIN_CONFIDENCE", "0.3")
                ),
                promote_step=float(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_PROMOTE_STEP", "0.2")
                ),
                demote_step=float(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_DEMOTE_STEP", "0.25")
                ),
                promote_threshold=float(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_PROMOTE_THRESHOLD", "0.8")
                ),
                reject_floor=float(
                    os.getenv("PERSONAL_AGENT_REFLECTION_REPLAY_REJECT_FLOOR", "0.2")
                ),
            ),
        )


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv(raw: str) -> tuple[str, ...]:
    """Parse a comma-separated env value into a tuple of trimmed tokens."""
    if not raw.strip():
        return ()
    return tuple(token.strip() for token in raw.split(",") if token.strip())


def _parse_json_env(name: str) -> dict[str, Any]:
    """Parse a JSON-object env var into a dict; empty/invalid yields {}."""
    import json
    import os

    raw = (os.getenv(name) or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_api_keys(raw: str) -> dict[str, str]:
    """Parse 'key1:user1,key2:user2' into {key1: user1, key2: user2}."""
    result: dict[str, str] = {}
    if not raw.strip():
        return result
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        key, user = pair.split(":", 1)
        result[key.strip()] = user.strip()
    return result


def _parse_cors_origins(raw: str) -> list[str]:
    """Parse comma-separated origins into a list."""
    if not raw.strip():
        return []
    return [origin.strip() for origin in raw.split(",") if origin.strip()]
