from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from dotenv import load_dotenv


class Settings(BaseModel):
    data_dir: Path = Path("./data")
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

    @classmethod
    def from_env(cls) -> "Settings":
        import os

        load_dotenv()
        return cls(
            data_dir=Path(os.getenv("PERSONAL_AGENT_DATA_DIR", "./data")),
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
        )


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
