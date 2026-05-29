from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.config import Settings
from ..graphiti.store import GraphitiStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from .runtime import AgentRuntime

if TYPE_CHECKING:
    from ..capture import CaptureService


class AgentService(AgentRuntime):
    """Compatibility entry point that wires stores and then behaves as runtime."""

    def __init__(
        self, settings: Settings | None = None, capture_service: "CaptureService | None" = None
    ) -> None:
        resolved_settings = settings or Settings.from_env()
        if not resolved_settings.postgres_url:
            raise ValueError("PERSONAL_AGENT_POSTGRES_URL is required for business persistence.")
        store = PostgresMemoryStore(resolved_settings.data_dir, resolved_settings.postgres_url)
        super().__init__(
            settings=resolved_settings,
            store=store,
            graph_store=GraphitiStore(resolved_settings),
            capture_service=capture_service,
        )
        self._runtime = self
