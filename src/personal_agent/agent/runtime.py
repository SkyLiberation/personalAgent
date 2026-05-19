from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langgraph.types import Command

from ..core.config import Settings
from ..core.models import EntryInput
from ..graphiti.store import GraphitiStore
from ..memory import MemoryFacade
from ..storage.ask_history_store import AskHistoryStore
from ..storage.cross_session_store import CrossSessionStore
from ..storage.memory_store import LocalMemoryStore
from ..storage.pending_action_store import PendingActionStore
from ..tools import ToolRegistry
from .orchestration_graph import _build_checkpointer, build_entry_orchestration_graph
from .orchestration_models import AgentGraphState, AgentRunSnapshot
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

logger = logging.getLogger(__name__)


def _interrupt_payload_from_result(result: object) -> dict | None:
    """Extract the first LangGraph interrupt payload from an invoke result."""
    if not isinstance(result, dict) or "__interrupt__" not in result:
        return None

    interrupts = result.get("__interrupt__") or []
    if not interrupts:
        return {}

    interrupt_value = getattr(interrupts[0], "value", interrupts[0])
    if isinstance(interrupt_value, dict):
        return interrupt_value
    return {"message": str(interrupt_value)}


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
        # Orchestration graph — built lazily on first use
        self._orch_graph = None

    # ---- orchestration graph ----

    def _get_orch_graph(self):
        """Lazily build and cache the entry orchestration graph."""
        if self._orch_graph is None:
            checkpointer = _build_checkpointer(self.settings)
            self._orch_graph = build_entry_orchestration_graph(self, checkpointer=checkpointer)
            logger.info(
                "Entry orchestration graph built checkpoint_backend=%s",
                self.settings.langgraph_checkpoint_backend,
            )
        return self._orch_graph

    def execute_entry(
        self, entry_input: EntryInput, on_progress=None
    ) -> EntryResult:
        """Execute an entry through the LangGraph orchestration graph."""
        graph = self._get_orch_graph()
        from .orchestration_models import AgentGraphState, _new_run_id, _new_thread_id

        normalized_user = entry_input.user_id or self.settings.default_user
        normalized_session = entry_input.session_id or "default"
        run_id = _new_run_id()
        thread_id = _new_thread_id(normalized_user, normalized_session, run_id)

        initial_state = AgentGraphState(
            run_id=run_id,
            thread_id=thread_id,
            user_id=normalized_user,
            session_id=normalized_session,
            entry_input=entry_input.model_copy(
                update={
                    "user_id": normalized_user,
                    "session_id": normalized_session,
                }
            ),
            entry_text=entry_input.text or "",
        )

        config = {"configurable": {"thread_id": thread_id}}

        invoke_result = graph.invoke(initial_state, config)
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            state_snapshot = invoke_result if isinstance(invoke_result, dict) else {}

            logger.info(
                "Graph interrupted for confirmation run_id=%s thread_id=%s step=%s",
                run_id, thread_id, interrupt_data.get("step_id", "?"),
            )
            return EntryResult(
                intent=str(state_snapshot.get("intent") or "unknown"),
                reason="操作需要用户确认",
                reply_text=str(interrupt_data.get("message", "此操作需要您的确认。")),
                plan_steps=list(state_snapshot.get("plan_steps") or []),
                execution_trace=list(state_snapshot.get("execution_trace") or []),
                run_id=run_id,
                thread_id=thread_id,
                pending_confirmation=interrupt_data,
                run_status="waiting_confirmation",
                events=[
                    e.model_dump(mode="json") if hasattr(e, "model_dump") else e
                    for e in (state_snapshot.get("events") or initial_state.events)
                ],
            )

        result_state = AgentGraphState.model_validate(invoke_result)

        # Map graph state back to EntryResult for API compatibility
        reply_text = result_state.answer or "暂时没有可执行的结果。"

        capture_result = None
        ask_result = None
        if result_state.intent in ("capture_text", "capture_link", "capture_file"):
            # Capture results come through entry graph internals
            pass
        elif result_state.intent == "ask":
            ask_result = AskResult(
                answer=reply_text,
                citations=result_state.citations,
                matches=[],
                session_id=normalized_session,
            )

        return EntryResult(
            intent=result_state.intent,
            reason=result_state.intent_reason or "未提供路由说明。",
            reply_text=reply_text,
            capture_result=capture_result,
            ask_result=ask_result,
            plan_steps=result_state.plan_steps,
            execution_trace=result_state.execution_trace,
            run_id=run_id,
            thread_id=thread_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in result_state.events],
        )

    def resume_entry(
        self, run_id: str, thread_id: str, decision: str, user_id: str,
    ) -> EntryResult:
        """Resume a graph run that was interrupted for HITL confirmation.

        Args:
            run_id: The run to resume.
            thread_id: Thread ID from the original run config.
            decision: ``"confirm"`` or ``"reject"``.
            user_id: Authenticated user making the decision.

        Returns:
            Final EntryResult after graph completion.
        """
        graph = self._get_orch_graph()
        config = {"configurable": {"thread_id": thread_id}}
        resume_value = {"decision": decision, "user_id": user_id}

        logger.info(
            "Resuming graph run_id=%s thread_id=%s decision=%s",
            run_id, thread_id, decision,
        )

        result_state = AgentGraphState.model_validate(
            graph.invoke(Command(resume=resume_value), config)
        )

        reply_text = result_state.answer or "操作已完成。"

        return EntryResult(
            intent=result_state.intent,
            reason=result_state.intent_reason or "",
            reply_text=reply_text,
            plan_steps=result_state.plan_steps,
            execution_trace=result_state.execution_trace,
            run_id=run_id,
            thread_id=thread_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in result_state.events],
        )

    def get_run_snapshot(self, run_id: str) -> AgentRunSnapshot | None:
        """Return a read-only snapshot for a previously executed run."""
        if self._orch_graph is None:
            return None
        try:
            checkpointer = self._orch_graph.checkpointer
            # Pass None to list all checkpoint threads
            for ct in checkpointer.list(None, limit=500):
                tid: str = ct.config.get("configurable", {}).get("thread_id", "")
                if not tid or not tid.endswith(f":{run_id}"):
                    continue
                if ct.checkpoint and "channel_values" in ct.checkpoint:
                    cv = ct.checkpoint["channel_values"]
                    state = AgentGraphState.model_validate(cv)
                    return state.to_run_snapshot()
        except Exception:
            logger.debug("Could not retrieve run snapshot for run_id=%s", run_id, exc_info=True)
        return None

    def list_run_snapshots(
        self, user_id: str | None = None, limit: int = 50,
    ) -> list[AgentRunSnapshot]:
        """List recent run snapshots, optionally filtered by user."""
        if self._orch_graph is None:
            return []
        snapshots: list[AgentRunSnapshot] = []
        try:
            checkpointer = self._orch_graph.checkpointer
            # Pass None to list all checkpoint threads
            seen: set[str] = set()
            for ct in checkpointer.list(None, limit=limit * 2):
                tid: str = ct.config.get("configurable", {}).get("thread_id", "")
                if not tid:
                    continue
                if user_id and not tid.startswith(f"{user_id}:"):
                    continue
                if tid in seen:
                    continue
                seen.add(tid)
                if ct.checkpoint and "channel_values" in ct.checkpoint:
                    cv = ct.checkpoint["channel_values"]
                    state = AgentGraphState.model_validate(cv)
                    snapshots.append(state.to_run_snapshot())
                if len(snapshots) >= limit:
                    break
        except Exception:
            logger.debug("Could not list run snapshots", exc_info=True)
        return snapshots

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
