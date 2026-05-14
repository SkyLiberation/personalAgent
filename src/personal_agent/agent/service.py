from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.config import Settings
from ..graphiti.store import GraphitiStore
from ..storage.ask_history_store import AskHistoryStore
from ..storage.memory_store import LocalMemoryStore
from .runtime import AgentRuntime

if TYPE_CHECKING:
    from ..capture import CaptureService


class AgentService(AgentRuntime):
    """Compatibility entry point that wires stores and then behaves as runtime."""

    def __init__(
        self, settings: Settings | None = None, capture_service: "CaptureService | None" = None
    ) -> None:
        resolved_settings = settings or Settings.from_env()
        super().__init__(
            settings=resolved_settings,
            store=LocalMemoryStore(resolved_settings.data_dir),
            graph_store=GraphitiStore(resolved_settings),
            ask_history_store=AskHistoryStore(resolved_settings.postgres_url),
            capture_service=capture_service,
        )
        self._runtime = self
