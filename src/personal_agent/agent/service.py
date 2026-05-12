from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.config import Settings
from ..core.models import AskHistoryRecord, EntryInput, KnowledgeNote, PendingAction
from ..graphiti.store import GraphitiStore
from ..storage.ask_history_store import AskHistoryStore
from ..storage.memory_store import LocalMemoryStore
from ..tools import ToolSpec, ToolResult
from .runtime import (
    AgentRuntime,
    AskResult,
    CaptureResult,
    DigestResult,
    EntryResult,
    ResetResult,
)

if TYPE_CHECKING:
    from ..capture import CaptureService


class AgentService:
    """Thin facade over AgentRuntime that preserves backward-compatible public API.

    AgentService wires together settings, stores, and services, then delegates
    all execution to AgentRuntime. This keeps the public API stable while the
    runtime implementation can evolve independently.
    """

    def __init__(
        self, settings: Settings | None = None, capture_service: "CaptureService | None" = None
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.store = LocalMemoryStore(self.settings.data_dir)
        self.graph_store = GraphitiStore(self.settings)
        self.ask_history_store = AskHistoryStore(self.settings.postgres_url)
        self.capture_service = capture_service
        self._runtime = AgentRuntime(
            settings=self.settings,
            store=self.store,
            graph_store=self.graph_store,
            ask_history_store=self.ask_history_store,
            capture_service=capture_service,
        )

    @property
    def memory(self):
        return self._runtime.memory

    def list_tools(self) -> list[ToolSpec]:
        return self._runtime.list_tools()

    def execute_tool(self, name: str, **kwargs: object) -> ToolResult:
        return self._runtime.execute_tool(name, **kwargs)

    def capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
        attempt_graph: bool = True,
    ) -> CaptureResult:
        return self._runtime.execute_capture(
            text=text,
            source_type=source_type,
            user_id=user_id,
            source_ref=source_ref,
            attempt_graph=attempt_graph,
        )

    def ask(
        self, question: str, user_id: str | None = None, session_id: str | None = None
    ) -> AskResult:
        return self._runtime.execute_ask(
            question=question, user_id=user_id, session_id=session_id
        )

    def digest(self, user_id: str | None = None) -> DigestResult:
        return self._runtime.execute_digest(user_id=user_id)

    def entry(self, entry_input: EntryInput, on_progress = None) -> EntryResult:
        return self._runtime.execute_entry(entry_input, on_progress=on_progress)

    def list_notes(self, user_id: str | None = None) -> list[KnowledgeNote]:
        return self._runtime.list_notes(user_id=user_id)

    def health(self) -> dict[str, object]:
        return self._runtime.health()

    def list_ask_history(
        self, user_id: str | None = None, limit: int = 20, session_id: str | None = None
    ) -> list[AskHistoryRecord]:
        return self._runtime.list_ask_history(
            user_id=user_id, limit=limit, session_id=session_id
        )

    def reset_user_data(self, user_id: str | None = None) -> ResetResult:
        return self._runtime.reset_user_data(user_id=user_id)

    def sync_note_to_graph(self, note_id: str) -> bool:
        return self._runtime.sync_note_to_graph(note_id)

    def list_pending_actions(
        self, user_id: str | None = None, status: str | None = None
    ) -> list[PendingAction]:
        return self._runtime.list_pending_actions(user_id, status)

    def confirm_pending_action(
        self, action_id: str, token: str, user_id: str | None = None
    ) -> PendingAction | None:
        return self._runtime.confirm_pending_action(action_id, token, user_id)

    def reject_pending_action(
        self, action_id: str, user_id: str | None = None, reason: str = ""
    ) -> PendingAction | None:
        return self._runtime.reject_pending_action(action_id, user_id, reason)
