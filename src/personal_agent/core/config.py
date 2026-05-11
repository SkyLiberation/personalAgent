from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv


class Settings(BaseModel):
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    embedding_provider: str = "local"
    llm_provider: str = "stub"
    default_user: str = "default"
    graphiti_enabled: bool = False
    graphiti_uri: str = "bolt://localhost:7687"
    graphiti_user: str = "neo4j"
    graphiti_password: str = "password"
    graphiti_group_prefix: str = "personal-agent"
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4.1-mini"
    openai_small_model: str = "gpt-4.1-nano"
    openai_embedding_model: str = "text-embedding-3-small"
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    firecrawl_api_key: str | None = None
    firecrawl_base_url: str = "https://api.firecrawl.dev"
    firecrawl_timeout_ms: int = 60000
    postgres_url: str | None = None
    feishu_enabled: bool = False
    feishu_app_id: str | None = None
    feishu_app_secret: str | None = None
    feishu_verification_token: str | None = None
    feishu_base_url: str = "https://open.feishu.cn"
    feishu_use_default_user: bool = True
    graph_sync_max_attempts: int = 3
    graph_sync_initial_backoff_seconds: float = 2.0
    graph_sync_backoff_multiplier: float = 2.0
    graph_sync_max_backoff_seconds: float = 20.0
    max_verify_retries: int = 1
    api_keys: dict[str, str] = {}
    rate_limit_requests: int = 60
    rate_limit_window_seconds: int = 60
    cors_origins: list[str] = ["http://localhost:3000"]

    @classmethod
    def from_env(cls) -> "Settings":
        import os

        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("PERSONAL_AGENT_DATA_DIR", "./data")),
            log_level=os.getenv("PERSONAL_AGENT_LOG_LEVEL", "INFO"),
            embedding_provider=os.getenv("PERSONAL_AGENT_EMBEDDING_PROVIDER", "local"),
            llm_provider=os.getenv("PERSONAL_AGENT_LLM_PROVIDER", "stub"),
            default_user=os.getenv("PERSONAL_AGENT_DEFAULT_USER", "default"),
            graphiti_enabled=_as_bool(os.getenv("PERSONAL_AGENT_GRAPHITI_ENABLED", "false")),
            graphiti_uri=os.getenv("PERSONAL_AGENT_GRAPHITI_URI", "bolt://localhost:7687"),
            graphiti_user=os.getenv("PERSONAL_AGENT_GRAPHITI_USER", "neo4j"),
            graphiti_password=os.getenv("PERSONAL_AGENT_GRAPHITI_PASSWORD", "password"),
            graphiti_group_prefix=os.getenv("PERSONAL_AGENT_GRAPHITI_GROUP_PREFIX", "personal-agent"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            openai_base_url=os.getenv("OPENAI_BASE_URL"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            openai_small_model=os.getenv("OPENAI_SMALL_MODEL", "gpt-4.1-nano"),
            openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
            embedding_api_key=os.getenv("EMBEDDING_API_KEY"),
            embedding_base_url=os.getenv("EMBEDDING_BASE_URL"),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY"),
            firecrawl_base_url=os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"),
            firecrawl_timeout_ms=int(os.getenv("FIRECRAWL_TIMEOUT_MS", "60000")),
            postgres_url=os.getenv("PERSONAL_AGENT_POSTGRES_URL"),
            feishu_enabled=_as_bool(os.getenv("PERSONAL_AGENT_FEISHU_ENABLED", "false")),
            feishu_app_id=os.getenv("FEISHU_APP_ID"),
            feishu_app_secret=os.getenv("FEISHU_APP_SECRET"),
            feishu_verification_token=os.getenv("FEISHU_VERIFICATION_TOKEN"),
            feishu_base_url=os.getenv("FEISHU_BASE_URL", "https://open.feishu.cn"),
            feishu_use_default_user=_as_bool(os.getenv("PERSONAL_AGENT_FEISHU_USE_DEFAULT_USER", "true")),
            graph_sync_max_attempts=int(os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_ATTEMPTS", "3")),
            graph_sync_initial_backoff_seconds=float(
                os.getenv("PERSONAL_AGENT_GRAPH_SYNC_INITIAL_BACKOFF_SECONDS", "2.0")
            ),
            graph_sync_backoff_multiplier=float(
                os.getenv("PERSONAL_AGENT_GRAPH_SYNC_BACKOFF_MULTIPLIER", "2.0")
            ),
            graph_sync_max_backoff_seconds=float(
                os.getenv("PERSONAL_AGENT_GRAPH_SYNC_MAX_BACKOFF_SECONDS", "20.0")
            ),
            max_verify_retries=int(os.getenv("AGENT_MAX_VERIFY_RETRIES", "1")),
            api_keys=_parse_api_keys(os.getenv("PERSONAL_AGENT_API_KEYS", "")),
            rate_limit_requests=int(os.getenv("PERSONAL_AGENT_RATE_LIMIT_REQUESTS", "60")),
            rate_limit_window_seconds=int(os.getenv("PERSONAL_AGENT_RATE_LIMIT_WINDOW_SECONDS", "60")),
            cors_origins=_parse_cors_origins(os.getenv("PERSONAL_AGENT_CORS_ORIGINS", "http://localhost:3000")),
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
