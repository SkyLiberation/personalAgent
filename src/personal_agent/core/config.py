from __future__ import annotations

from pathlib import Path

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
    search_min_score: float = 0.0

    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_small_model: str | None = None

    sync_max_attempts: int = 3
    sync_initial_backoff_seconds: float = 2.0
    sync_backoff_multiplier: float = 2.0
    sync_max_backoff_seconds: float = 20.0

    add_episode_timeout_seconds: float = 900.0
    search_timeout_seconds: float = 45.0
    episode_max_chars: int = 8000
    content_filter_fallback: bool = True


class OpenAIConfig(_StrictBase):
    api_key: str | None = None
    base_url: str | None = None
    model: str = "gpt-4.1-mini"
    small_model: str = "gpt-4.1-nano"
    embedding_model: str = "text-embedding-3-small"
    timeout_seconds: float = 30.0
    max_retries: int = 2
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None


class FirecrawlConfig(_StrictBase):
    api_key: str | None = None
    base_url: str = "https://api.firecrawl.dev"
    timeout_ms: int = 60000


class FeishuConfig(_StrictBase):
    enabled: bool = False
    app_id: str | None = None
    app_secret: str | None = None
    base_url: str = "https://open.feishu.cn"
    use_default_user: bool = True


class WebApiConfig(_StrictBase):
    api_keys: dict[str, str] = Field(default_factory=dict)
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])


class LangExtractConfig(_StrictBase):
    """LangExtract pre-extraction layer.

    Decoupled from OpenAIConfig (DeepSeek) and GraphitiConfig (Kimi) so the
    extraction layer can target a model that supports OpenAI-style structured
    outputs (e.g. qwen3-coder-flash) without disturbing the other LLM paths.
    """

    enabled: bool = False
    api_key: str | None = None
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model_id: str = "qwen3-coder-flash"
    max_char_buffer: int = 2000
    extraction_passes: int = 1
    max_workers: int = 4
    min_doc_chars: int = 500
    fallback_on_error: bool = True


class Settings(_StrictBase):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    embedding_provider: str = "local"
    llm_provider: str = "stub"
    default_user: str = "default"
    postgres_url: str | None = None
    max_verify_retries: int = 1

    graphiti: GraphitiConfig = Field(default_factory=GraphitiConfig)
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    firecrawl: FirecrawlConfig = Field(default_factory=FirecrawlConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    web: WebApiConfig = Field(default_factory=WebApiConfig)
    langextract: LangExtractConfig = Field(default_factory=LangExtractConfig)

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
            openai=OpenAIConfig(
                api_key=os.getenv("OPENAI_API_KEY"),
                base_url=os.getenv("OPENAI_BASE_URL"),
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
                small_model=os.getenv("OPENAI_SMALL_MODEL", "gpt-4.1-nano"),
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
            firecrawl=FirecrawlConfig(
                api_key=os.getenv("FIRECRAWL_API_KEY"),
                base_url=os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"),
                timeout_ms=int(os.getenv("FIRECRAWL_TIMEOUT_MS", "60000")),
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
            web=WebApiConfig(
                api_keys=_parse_api_keys(os.getenv("PERSONAL_AGENT_API_KEYS", "")),
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
            langextract=LangExtractConfig(
                enabled=_as_bool(
                    os.getenv("PERSONAL_AGENT_EXTRACT_ENABLED", "false")
                ),
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
                    os.getenv("PERSONAL_AGENT_EXTRACT_MAX_CHAR_BUFFER", "2000")
                ),
                extraction_passes=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_PASSES", "1")
                ),
                max_workers=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MAX_WORKERS", "4")
                ),
                min_doc_chars=int(
                    os.getenv("PERSONAL_AGENT_EXTRACT_MIN_DOC_CHARS", "500")
                ),
                fallback_on_error=_as_bool(
                    os.getenv("PERSONAL_AGENT_EXTRACT_FALLBACK_ON_ERROR", "true")
                ),
            ),
        )


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
