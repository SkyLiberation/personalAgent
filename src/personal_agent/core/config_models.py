from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
    # When False (default), a parent note with no graph-worthy chunks is synced
    # to the graph in the background via the worker queue instead of blocking
    # the capture call. Set True only for CLI/tests that need the note in the
    # graph synchronously on return. Foreground sync can block for up to
    # add_episode_timeout_seconds per note (Graphiti add_episode over Neo4j),
    # which is what hung the solidify→capture SSE stream in production.
    parent_note_sync_foreground: bool = False


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

    The router uses the OpenAI Responses API with Pydantic parsing, so it needs
    an endpoint that supports ``responses.parse`` (e.g. gpt-5.4-mini). This is kept
    separate from ``OpenAIConfig`` (which may point at an endpoint without
    json_schema support, such as DeepSeek) so the router can target a
    compatible model without disturbing the other LLM paths.

    ``model`` is exposed as ``small_model`` too for the shared LLM adapters.
    """

    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-5.4-mini"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    extra_body: dict[str, Any] = Field(default_factory=dict)

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


class KnowledgeGapConfig(_StrictBase):
    """Proactive knowledge-gap follow-up.

    Reuses the review-digest subscriptions (same chat targets) but runs on its
    own schedule/cadence. ``max_gaps_per_run`` bounds how many questions a
    single delivery may contain so the agent never floods the user.
    """

    enabled: bool = False
    schedule_time: str = "20:00"
    scheduler_enabled: bool = False
    scheduler_tick_seconds: int = 300
    max_gaps_per_run: int = 3
    min_entity_degree: int = 1
    recent_note_limit: int = 30


class ResearchConfig(_StrictBase):
    scheduler_enabled: bool = False
    scheduler_tick_seconds: int = 60
    max_queries: int = 5
    max_search_results: int = 30
    max_fulltext_fetches: int = 5
    max_tool_calls: int = 15


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
    # Answer grounding verifier. "heuristic" = lexical overlap + negation flip
    # (default, unchanged behavior); "entailment" = three-way per-claim
    # entailment judge (entailed/contradicted/not_enough_info). See
    # agent/verifier.create_answer_verifier and agent/entailment.py.
    verifier: str = "heuristic"
    # Contrastive retrieval: when verification flags contradicted / unsupported
    # claims, actively recall opposing evidence and re-verify (reactive hook in
    # the verification stage). Off by default — it adds a retrieval round-trip.
    # See agent/ask/retrievers.ContrastiveRetriever.
    contrastive_retrieval: bool = False
    candidate_enricher: str = "parent_child"
    parent_child_top_n: int = 3
    parent_child_min_overlap: int = 2
    neighbor_chunk_window: int = 0
    graph_note_evidence_mode: str = "all"
    graph_note_evidence_min_overlap: int = 2
    context_max_items: int = 12
    context_char_budget: int = 5000
    # MMR diversity weight for prompt selection: 1.0 = pure relevance (greedy),
    # lower diversifies harder against near-duplicate content. See
    # core/evidence.select_ranked_evidence.
    context_mmr_lambda: float = 0.7
    # Extractive sentence-level compression of long note/chunk snippets before
    # selection. 0 disables; otherwise the max sentences kept per snippet.
    context_compress_max_sentences: int = 3
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


class GuardrailsConfig(_StrictBase):
    """Content guardrails: prompt-injection / PII / sensitive-output handling.

    Default ``mode='sanitize'`` neutralizes/redacts and lets content through;
    only ``mode='block'`` rejects high-confidence malicious input. ``log_only``
    records verdicts without changing content (rollout/observation phase).
    """

    enabled: bool = True
    mode: str = "sanitize"  # sanitize | block | log_only
    redact_pii: bool = True


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

