"""Build the real service used by opt-in live scenario tests."""

from personal_agent.infra.structured_model import build_structured_model_client
from personal_agent.kernel.config import Settings
from personal_agent.orchestration.service import AgentService


def build_real_service() -> AgentService | None:
    try:
        settings = Settings.from_env()
    except Exception:
        return None
    if not settings.postgres_url:
        return None
    if build_structured_model_client(settings.structured, settings.langsmith) is None:
        return None
    try:
        return AgentService(settings)
    except Exception:
        return None


__all__ = ["build_real_service"]
