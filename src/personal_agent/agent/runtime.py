from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.config import Settings
from ..core.models import EntryInput
from ..graphiti.store import GraphitiStore
from ..memory import MemoryFacade
from ..storage.ask_history_store import AskHistoryStore
from ..storage.cross_session_store import CrossSessionStore
from ..storage.memory_store import LocalMemoryStore
from ..storage.pending_action_store import PendingActionStore
from ..tools import ToolRegistry
from .planner import DefaultTaskPlanner
from .plan_validator import PlanValidator
from .react_runner import ReActStepRunner
from .replanner import Replanner
from .router import DefaultIntentRouter
from .runtime_admin import RuntimeAdminMixin
from .runtime_ask import RuntimeAskMixin
from .runtime_capture import RuntimeCaptureMixin
from .runtime_entry import RuntimeEntryMixin
from .runtime_helpers import (
    _annotate_answer,
    _best_snippet,
    _evidence_content,
    _extract_question_keywords,
    _format_graph_relation,
    _graph_episode_uuids,
    _graph_fact_lines,
    _graph_facts_by_episode,
    _merge_citations,
    _merge_notes,
    _split_sentences,
    _tokenize_for_overlap,
    _top_sentences,
)
from .runtime_llm import RuntimeLlmMixin
from .runtime_results import (
    AskResult,
    CaptureResult,
    DigestResult,
    EntryResult,
    ResetResult,
    RetryResult,
)
from .runtime_tools import RuntimeToolsMixin
from .verifier import AnswerVerifier

if TYPE_CHECKING:
    from ..capture import CaptureService


class AgentRuntime(
    RuntimeToolsMixin,
    RuntimeCaptureMixin,
    RuntimeAskMixin,
    RuntimeEntryMixin,
    RuntimeAdminMixin,
    RuntimeLlmMixin,
):
    """Unified execution runtime for capture / ask / digest / entry operations.

    The public runtime object remains the integration point while behavior is
    split across focused inherited method groups to keep each module small and
    reviewable.
    """

    def __init__(
        self,
        settings: Settings,
        store: LocalMemoryStore,
        graph_store: GraphitiStore,
        ask_history_store: AskHistoryStore,
        capture_service: "CaptureService | None" = None,
        pending_action_store: PendingActionStore | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.graph_store = graph_store
        self.ask_history_store = ask_history_store
        self.pending_action_store = pending_action_store or PendingActionStore(settings.data_dir)
        self.capture_service = capture_service
        self._intent_router = DefaultIntentRouter(settings)
        self._tool_registry = ToolRegistry()
        self._register_tools()
        self._planner = DefaultTaskPlanner(settings, tool_registry=self._tool_registry)
        self._cross_session = CrossSessionStore(settings.data_dir)
        self.memory = MemoryFacade(store, ask_history_store, cross_session_store=self._cross_session)
        self._verifier = AnswerVerifier()
        self._plan_validator = PlanValidator(tool_registry=self._tool_registry)
        self._replanner = Replanner(settings)
        self._react_runner = ReActStepRunner(
            tool_registry=self._tool_registry,
            memory=self.memory,
            settings=settings,
        )

    def capture(
        self,
        text: str,
        source_type: str = "text",
        user_id: str | None = None,
        source_ref: str | None = None,
    ) -> CaptureResult:
        return self.execute_capture(
            text=text,
            source_type=source_type,
            user_id=user_id,
            source_ref=source_ref,
        )

    def ask(
        self, question: str, user_id: str | None = None, session_id: str | None = None
    ) -> AskResult:
        return self.execute_ask(question=question, user_id=user_id, session_id=session_id)

    def digest(self, user_id: str | None = None) -> DigestResult:
        return self.execute_digest(user_id=user_id)

    def entry(self, entry_input: EntryInput, on_progress=None) -> EntryResult:
        return self.execute_entry(entry_input, on_progress=on_progress)


__all__ = [
    "AgentRuntime",
    "AskResult",
    "CaptureResult",
    "DigestResult",
    "EntryResult",
    "ResetResult",
    "RetryResult",
    "_annotate_answer",
    "_best_snippet",
    "_evidence_content",
    "_extract_question_keywords",
    "_format_graph_relation",
    "_graph_episode_uuids",
    "_graph_fact_lines",
    "_graph_facts_by_episode",
    "_merge_citations",
    "_merge_notes",
    "_split_sentences",
    "_tokenize_for_overlap",
    "_top_sentences",
]
