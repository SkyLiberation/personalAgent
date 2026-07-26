from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any

from dotenv import load_dotenv

from personal_agent.kernel.config_models import (
    DEFAULT_GENERATIVE_MODEL,
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
    MCPServerConfig,
    MCPToolConfig,
    MicrosoftGraphRagConfig,
    OpenAIConfig,
    PolicyConfig,
    ReflectionReplaySettings,
    ResearchConfig,
    ReviewDigestConfig,
    ShortTermMemoryConfig,
    StructuredConfig,
    WebApiConfig,
    WebSearchConfig,
)


def settings_from_env(settings_cls: type):
    import os

    if not _as_bool(os.getenv("PYTHON_DOTENV_DISABLED", "false")):
        load_dotenv(override=True)
    structured_api_key = (
        os.getenv("STRUCTURED_API_KEY")
        or os.getenv("ROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    structured_base_url = (
        os.getenv("STRUCTURED_BASE_URL")
        or os.getenv("ROUTER_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
    )
    structured_model = (
        os.getenv("STRUCTURED_MODEL")
        or os.getenv("ROUTER_MODEL")
        or DEFAULT_GENERATIVE_MODEL
    )
    return settings_cls(
        data_dir=Path(os.getenv("PERSONAL_AGENT_DATA_DIR", "./data")),
        log_level=os.getenv("PERSONAL_AGENT_LOG_LEVEL", "INFO"),
        embedding_provider=os.getenv("PERSONAL_AGENT_EMBEDDING_PROVIDER", "local"),
        llm_provider=os.getenv("PERSONAL_AGENT_LLM_PROVIDER", "stub"),
        default_user=os.getenv("PERSONAL_AGENT_DEFAULT_USER", "default"),
        postgres_url=os.getenv("PERSONAL_AGENT_POSTGRES_URL"),
        max_verify_retries=int(os.getenv("AGENT_MAX_VERIFY_RETRIES", "1")),
        interaction_loop=InteractionLoopConfig(
            policy_revision=os.getenv("PERSONAL_AGENT_INTERACTION_POLICY_REVISION", "interaction-loop-v1"),
            max_model_turns=int(os.getenv("PERSONAL_AGENT_INTERACTION_MAX_MODEL_TURNS", "8")),
            max_tool_calls=int(os.getenv("PERSONAL_AGENT_INTERACTION_MAX_TOOL_CALLS", "12")),
            max_agent_calls=int(os.getenv("PERSONAL_AGENT_INTERACTION_MAX_AGENT_CALLS", "4")),
            max_total_tokens=int(os.getenv("PERSONAL_AGENT_INTERACTION_MAX_TOTAL_TOKENS", "32000")),
            max_concurrency=int(os.getenv("PERSONAL_AGENT_INTERACTION_MAX_CONCURRENCY", "4")),
        ),
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
            llm_api_key=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_API_KEY")
            or structured_api_key,
            llm_base_url=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_BASE_URL")
            or structured_base_url,
            llm_model=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_MODEL")
            or structured_model,
            llm_small_model=os.getenv("PERSONAL_AGENT_GRAPHITI_LLM_SMALL_MODEL")
            or structured_model,
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
            completion_model=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_MODEL")
            or structured_model,
            completion_api_key=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_KEY")
            or structured_api_key,
            completion_api_base=os.getenv("PERSONAL_AGENT_MS_GRAPHRAG_COMPLETION_API_BASE")
            or structured_base_url,
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
            api_key=os.getenv("OPENAI_API_KEY") or structured_api_key,
            base_url=os.getenv("OPENAI_BASE_URL") or structured_base_url,
            model=os.getenv("OPENAI_MODEL") or structured_model,
            small_model=os.getenv("OPENAI_SMALL_MODEL") or structured_model,
            vision_model=os.getenv("OPENAI_VISION_MODEL", ""),
            transcription_model=os.getenv("OPENAI_TRANSCRIPTION_MODEL", "whisper-1"),
            embedding_model=os.getenv(
                "OPENAI_EMBEDDING_MODEL", "BAAI/bge-m3"
            ),
            timeout_seconds=float(
                os.getenv("PERSONAL_AGENT_OPENAI_TIMEOUT_SECONDS", "30")
            ),
            max_retries=int(os.getenv("PERSONAL_AGENT_OPENAI_MAX_RETRIES", "2")),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY"),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL"),
        ),
        structured=StructuredConfig(
            api_key=structured_api_key,
            base_url=structured_base_url,
            model=structured_model,
            timeout_seconds=float(
                os.getenv("PERSONAL_AGENT_STRUCTURED_TIMEOUT_SECONDS")
                or os.getenv("PERSONAL_AGENT_ROUTER_TIMEOUT_SECONDS", "60")
            ),
            max_retries=int(
                os.getenv("PERSONAL_AGENT_STRUCTURED_MAX_RETRIES")
                or os.getenv("PERSONAL_AGENT_ROUTER_MAX_RETRIES", "2")
            ),
            extra_body=_parse_json_env("STRUCTURED_EXTRA_BODY")
            or _parse_json_env("ROUTER_EXTRA_BODY"),
        ),
        firecrawl=FirecrawlConfig(
            api_key=os.getenv("FIRECRAWL_API_KEY"),
            base_url=os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"),
            timeout_ms=int(os.getenv("FIRECRAWL_TIMEOUT_MS", "60000")),
        ),
        gpt_researcher_a2a=GPTResearcherA2AConfig(
            enabled=_as_bool(os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENABLED", "false")),
            endpoint=os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_ENDPOINT", "http://127.0.0.1:8001/a2a"),
            agent_card_url=os.getenv(
                "PERSONAL_AGENT_GPT_RESEARCHER_A2A_AGENT_CARD_URL",
                "http://127.0.0.1:8001/.well-known/agent-card.json",
            ),
            timeout_seconds=float(
                os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_TIMEOUT_SECONDS", "120")
            ),
            report_type=os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_TYPE", "research_report"),
            report_source=os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_REPORT_SOURCE", "web"),
            tone=os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_TONE", "Objective"),
            max_search_results=_parse_optional_int(
                os.getenv("PERSONAL_AGENT_GPT_RESEARCHER_A2A_MAX_SEARCH_RESULTS", "")
            ),
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
            or structured_api_key,
            base_url=os.getenv("PERSONAL_AGENT_EXTRACT_BASE_URL")
            or structured_base_url
            or "https://n.tokeness.io/v1",
            model_id=os.getenv("PERSONAL_AGENT_EXTRACT_MODEL")
            or structured_model,
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
        mcp=_mcp_config_from_env(),
        enterprise_knowledge=EnterpriseKnowledgeConfig(
            raw_roots=tuple(
                Path(item)
                for item in _parse_csv(os.getenv(
                    "PERSONAL_AGENT_ENTERPRISE_KNOWLEDGE_RAW_ROOTS",
                    "D:/mySoft/workspace/personalWiki/raw",
                ))
            ),
            raw_file_globs=_parse_csv(
                os.getenv("PERSONAL_AGENT_ENTERPRISE_KNOWLEDGE_RAW_GLOBS", "*.md")
            ),
            raw_max_file_bytes=int(
                os.getenv("PERSONAL_AGENT_ENTERPRISE_KNOWLEDGE_RAW_MAX_FILE_BYTES", "2000000")
            ),
        ),
        ask=AskConfig(
            graph_provider=os.getenv("PERSONAL_AGENT_ASK_GRAPH_PROVIDER", "graphiti"),
            reranker=os.getenv("PERSONAL_AGENT_ASK_RERANKER", "support"),
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
            support_rerank_weight=float(
                os.getenv("PERSONAL_AGENT_ASK_SUPPORT_RERANK_WEIGHT", "0.18")
            ),
            support_rerank_direct_coverage=float(
                os.getenv("PERSONAL_AGENT_ASK_SUPPORT_RERANK_DIRECT_COVERAGE", "0.45")
            ),
            support_rerank_min_overlap_terms=int(
                os.getenv("PERSONAL_AGENT_ASK_SUPPORT_RERANK_MIN_OVERLAP_TERMS", "2")
            ),
            support_rerank_consensus_weight=float(
                os.getenv("PERSONAL_AGENT_ASK_SUPPORT_RERANK_CONSENSUS_WEIGHT", "0.04")
            ),
            llm_rerank_top_n=int(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_TOP_N", "20")
            ),
            llm_rerank_timeout_seconds=float(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_TIMEOUT_SECONDS", "20")
            ),
            llm_rerank_model=os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_MODEL"),
            llm_rerank_gated_min_candidates=int(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_MIN_CANDIDATES", "6")
            ),
            llm_rerank_gated_score_margin=float(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_SCORE_MARGIN", "0.0")
            ),
            llm_rerank_gated_low_score=float(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_LOW_SCORE", "0.45")
            ),
            llm_rerank_gated_dense_sparse_gap=int(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_DENSE_SPARSE_GAP", "8")
            ),
            llm_rerank_gated_min_support_coverage=float(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_MIN_SUPPORT_COVERAGE", "0.35")
            ),
            llm_rerank_gated_preserve_top_k=int(
                os.getenv("PERSONAL_AGENT_ASK_LLM_RERANK_GATED_PRESERVE_TOP_K", "0")
            ),
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


def _parse_optional_int(raw: str | None) -> int | None:
    value = (raw or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_mcp_config(raw: str) -> MCPConfig:
    """Parse MCP server registrations from a JSON env var.

    Expected shape:
    {
      "enabled": true,
      "servers": [
        {
          "server_id": "confluence",
          "transport": "http",
          "endpoint": "https://mcp.example/rpc",
          "authorization": "Bearer ...",
          "tools": [{
            "remote_name": "search_pages",
            "name": "enterprise.search_pages",
            "semantic_domains": ["docs"],
            "resource_types": ["page"],
            "operations": ["search"],
            "trust_level": "scoped",
            "credential_mode": "delegated_token",
            "data_egress_class": "content",
            "attestation_status": "pinned",
            "freshness_profile": "near_realtime"
          }]
        },
        {
          "server_id": "github",
          "transport": "stdio",
          "command": "docker",
          "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
          "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PAT}", "GITHUB_READ_ONLY": "1"},
          "tools": [{
            "remote_name": "search_code",
            "name": "github.search_code",
            "semantic_domains": ["codebase"],
            "resource_types": ["repository", "file", "code"],
            "operations": ["search"],
            "trust_level": "scoped",
            "credential_mode": "delegated_token",
            "data_egress_class": "content",
            "attestation_status": "pinned",
            "freshness_profile": "near_realtime"
          }]
        }
      ]
    }
    """
    if not raw.strip():
        return MCPConfig()
    import json

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("PERSONAL_AGENT_MCP_SERVERS must be valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValueError("PERSONAL_AGENT_MCP_SERVERS must be a JSON object.")
    raw_servers = parsed.get("servers", []) or []
    if not isinstance(raw_servers, list):
        raise ValueError("PERSONAL_AGENT_MCP_SERVERS.servers must be a list.")
    servers: list[MCPServerConfig] = []
    for server in raw_servers:
        if not isinstance(server, dict):
            raise ValueError("MCP server entry must be an object.")
        tools: list[MCPToolConfig] = []
        for item in server.get("tools", []) or []:
            if not isinstance(item, dict):
                raise ValueError("MCP tool entry must be an object.")
            tools.append(MCPToolConfig.model_validate(item))
        servers.append(MCPServerConfig.model_validate({
            **server,
            "tools": tuple(tools),
        }))
    return MCPConfig(
        enabled=_as_bool(str(parsed.get("enabled", False))),
        servers=tuple(servers),
    )


def _mcp_config_from_env() -> MCPConfig:
    """Parse generic MCP config and append opt-in first-party presets."""
    import os

    config = _parse_mcp_config(os.getenv("PERSONAL_AGENT_MCP_SERVERS", ""))
    presets = tuple(
        server
        for server in (
            _github_mcp_server_from_env(),
            _notion_mcp_server_from_env(),
        )
        if server is not None
    )
    if not presets:
        return config
    servers = list(config.servers)
    existing_ids = {server.server_id for server in servers}
    for preset in presets:
        if preset.server_id in existing_ids:
            continue
        servers.append(preset)
        existing_ids.add(preset.server_id)
    return MCPConfig(
        enabled=True,
        servers=tuple(servers),
    )


def _github_mcp_server_from_env() -> MCPServerConfig | None:
    """Build the official GitHub MCP server preset when explicitly enabled."""
    import os

    if not _as_bool(os.getenv("PERSONAL_AGENT_GITHUB_MCP_ENABLED", "false")):
        return None
    token_env = os.getenv("PERSONAL_AGENT_GITHUB_MCP_TOKEN_ENV", "GITHUB_PAT")
    image = os.getenv(
        "PERSONAL_AGENT_GITHUB_MCP_IMAGE",
        "ghcr.io/github/github-mcp-server",
    )
    command = os.getenv("PERSONAL_AGENT_GITHUB_MCP_COMMAND", "docker")
    args = _parse_json_list_env("PERSONAL_AGENT_GITHUB_MCP_ARGS")
    if not args:
        args = (
            "run",
            "-i",
            "--rm",
            "-e",
            "GITHUB_PERSONAL_ACCESS_TOKEN",
            "-e",
            "GITHUB_READ_ONLY",
            image,
        )
    tools = tuple(
        _github_mcp_tool_config(name)
        for name in _parse_csv(
            os.getenv(
                "PERSONAL_AGENT_GITHUB_MCP_TOOLS",
                "search_code,get_file_contents,search_repositories",
            )
        )
    )
    return MCPServerConfig(
        server_id=os.getenv("PERSONAL_AGENT_GITHUB_MCP_SERVER_ID", "github"),
        transport="stdio",
        command=command,
        args=args,
        env={
            "GITHUB_PERSONAL_ACCESS_TOKEN": f"${{{token_env}}}",
            "GITHUB_READ_ONLY": os.getenv("PERSONAL_AGENT_GITHUB_MCP_READ_ONLY", "1"),
        },
        timeout_seconds=float(os.getenv("PERSONAL_AGENT_GITHUB_MCP_TIMEOUT_SECONDS", "20")),
        tools=tools,
    )


def _github_mcp_tool_config(remote_name: str) -> MCPToolConfig:
    descriptions = {
        "search_code": "Search code in GitHub repositories that the configured token can read.",
        "get_file_contents": "Read file contents from a GitHub repository that the configured token can read.",
        "search_repositories": "Search GitHub repositories visible to the configured token.",
    }
    capability_by_remote = {
        "search_code": {
            "semantic_domains": ("codebase",),
            "resource_types": ("repository", "file", "code"),
            "operations": ("search",),
            "freshness_profile": "near_realtime",
            "provider_priority": 20,
            "examples": ({
                "user_task": "在 github/github-mcp-server 里 search_code 是在哪里实现的？",
                "tool": "github.search_code",
            },),
        },
        "get_file_contents": {
            "semantic_domains": ("codebase", "docs"),
            "resource_types": ("repository", "file"),
            "operations": ("read",),
            "freshness_profile": "near_realtime",
            "provider_priority": 20,
            "examples": ({
                "user_task": "读取 github/github-mcp-server 的 README.md",
                "tool": "github.get_file_contents",
            },),
        },
        "search_repositories": {
            "semantic_domains": ("codebase", "repository_discovery"),
            "resource_types": ("repository",),
            "operations": ("search",),
            "freshness_profile": "near_realtime",
            "provider_priority": 30,
            "examples": ({
                "user_task": "搜索 GitHub 上 stars:>10000 topic:agent language:python 的仓库",
                "tool": "github.search_repositories",
            },),
        },
    }
    capability = capability_by_remote.get(remote_name, {})
    return MCPToolConfig(
        remote_name=remote_name,
        name=f"github.{remote_name}",
        description=descriptions.get(remote_name),
        business_role="enterprise_knowledge_search",
        semantic_domains=capability.get("semantic_domains", ("codebase",)),
        resource_types=capability.get("resource_types", ("repository",)),
        operations=capability.get("operations", ("search",)),
        trust_level="scoped",
        credential_mode="delegated_token",
        data_egress_class="content",
        attestation_status="pinned",
        freshness_profile=capability.get("freshness_profile", "near_realtime"),
        output_contract="ToolResult",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
        provider_priority=capability.get("provider_priority"),
        examples=capability.get("examples", ()),
        exposure="public_agent",
        risk_level="low",
        side_effects=("external_network",),
        permission_scope="github:repo:read",
        audit_required=True,
        timeout_seconds=20.0,
        max_retries=1,
        retry_backoff_seconds=0.2,
        rate_limit_per_minute=30,
        allowed_domains=("github.com",),
    )


def _notion_mcp_server_from_env() -> MCPServerConfig | None:
    """Build the Notion MCP server preset when explicitly enabled."""
    import os

    if not _as_bool(os.getenv("PERSONAL_AGENT_NOTION_MCP_ENABLED", "false")):
        return None
    token_env = os.getenv("PERSONAL_AGENT_NOTION_MCP_TOKEN_ENV", "NOTION_TOKEN")
    command = os.getenv("PERSONAL_AGENT_NOTION_MCP_COMMAND") or (
        shutil.which("npx.cmd") or shutil.which("npx") or "npx"
    )
    args = _parse_json_list_env("PERSONAL_AGENT_NOTION_MCP_ARGS")
    if not args:
        args = ("-y", "@notionhq/notion-mcp-server")
    tools = tuple(
        _notion_mcp_tool_config(name)
        for name in _parse_csv(
            os.getenv(
                "PERSONAL_AGENT_NOTION_MCP_TOOLS",
                "API-post-search,API-retrieve-page-markdown",
            )
        )
    )
    return MCPServerConfig(
        server_id=os.getenv("PERSONAL_AGENT_NOTION_MCP_SERVER_ID", "notion"),
        transport="stdio",
        command=command,
        args=args,
        env={
            "NOTION_TOKEN": f"${{{token_env}}}",
        },
        timeout_seconds=float(os.getenv("PERSONAL_AGENT_NOTION_MCP_TIMEOUT_SECONDS", "20")),
        tools=tools,
    )


def _notion_mcp_tool_config(remote_name: str) -> MCPToolConfig:
    public_name_by_remote = {
        "API-post-search": "notion.search",
        "API-retrieve-page-markdown": "notion.retrieve_page_markdown",
    }
    descriptions = {
        "API-post-search": "Search pages and data sources visible to the configured Notion token.",
        "API-retrieve-page-markdown": "Read a Notion page's full content as Markdown.",
    }
    capability_by_remote = {
        "API-post-search": {
            "semantic_domains": ("workspace_knowledge", "docs"),
            "resource_types": ("page", "data_source"),
            "operations": ("search",),
            "provider_priority": 20,
            "examples": ({
                "user_task": "在 Notion 里搜索 Orion 项目的会议纪要",
                "tool": "notion.search",
            },),
        },
        "API-retrieve-page-markdown": {
            "semantic_domains": ("workspace_knowledge", "docs"),
            "resource_types": ("page",),
            "operations": ("read",),
            "provider_priority": 20,
            "examples": ({
                "user_task": "读取 Notion 页面并总结内容",
                "tool": "notion.retrieve_page_markdown",
            },),
        },
    }
    capability = capability_by_remote.get(remote_name, {})
    return MCPToolConfig(
        remote_name=remote_name,
        name=public_name_by_remote.get(remote_name, f"notion.{remote_name.replace('-', '_')}"),
        description=descriptions.get(remote_name),
        business_role="enterprise_knowledge_search",
        semantic_domains=capability.get("semantic_domains", ("workspace_knowledge",)),
        resource_types=capability.get("resource_types", ("page",)),
        operations=capability.get("operations", ("search",)),
        trust_level="scoped",
        credential_mode="delegated_token",
        data_egress_class="content",
        attestation_status="pinned",
        freshness_profile="near_realtime",
        output_contract="ToolResult",
        evidence_contract="provider_output",
        failure_semantics="return_typed_failure",
        provider_priority=capability.get("provider_priority"),
        examples=capability.get("examples", ()),
        exposure="public_agent",
        risk_level="low",
        side_effects=("external_network",),
        permission_scope="notion:workspace:read",
        audit_required=True,
        timeout_seconds=20.0,
        max_retries=1,
        retry_backoff_seconds=0.2,
        rate_limit_per_minute=30,
        allowed_domains=("notion.so", "api.notion.com"),
    )


def _parse_json_list_env(name: str) -> tuple[str, ...]:
    import json
    import os

    raw = (os.getenv(name) or "").strip()
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


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
