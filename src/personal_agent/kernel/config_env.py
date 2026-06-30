from __future__ import annotations

from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from personal_agent.kernel.config_models import (
    AskConfig,
    FeishuConfig,
    FirecrawlConfig,
    GraphitiConfig,
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


def settings_from_env(settings_cls: type):
    import os

    load_dotenv(override=True)
    return settings_cls(
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
        knowledge_gap=KnowledgeGapConfig(
            enabled=_as_bool(os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_ENABLED", "false")),
            schedule_time=os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_TIME", "20:00"),
            scheduler_enabled=_as_bool(
                os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_ENABLED", "false")
            ),
            scheduler_tick_seconds=int(
                os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_SCHEDULER_TICK_SECONDS", "300")
            ),
            max_gaps_per_run=int(
                os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_MAX_GAPS", "3")
            ),
            min_entity_degree=int(
                os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_MIN_DEGREE", "1")
            ),
            recent_note_limit=int(
                os.getenv("PERSONAL_AGENT_KNOWLEDGE_GAP_RECENT_NOTE_LIMIT", "30")
            ),
        ),
        research=ResearchConfig(
            scheduler_enabled=_as_bool(
                os.getenv("PERSONAL_AGENT_RESEARCH_SCHEDULER_ENABLED", "false")
            ),
            scheduler_tick_seconds=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_SCHEDULER_TICK_SECONDS", "60")
            ),
            max_queries=int(os.getenv("PERSONAL_AGENT_RESEARCH_MAX_QUERIES", "5")),
            max_exploration_queries=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_EXPLORATION_QUERIES", "3")
            ),
            max_verification_queries=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_VERIFICATION_QUERIES", "2")
            ),
            max_satisfaction_model_calls=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_SATISFACTION_MODEL_CALLS", "1")
            ),
            max_search_results=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_SEARCH_RESULTS", "30")
            ),
            max_fulltext_fetches=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_FULLTEXT_FETCHES", "5")
            ),
            max_tool_calls=int(
                os.getenv("PERSONAL_AGENT_RESEARCH_MAX_TOOL_CALLS", "15")
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
