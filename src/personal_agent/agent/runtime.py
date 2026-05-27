from __future__ import annotations

import logging
from typing import Callable, TYPE_CHECKING

from langgraph.types import Command

from ..core.config import Settings
from ..core.models import EntryInput
from ..graphiti.store import GraphitiStore
from ..memory import MemoryFacade
from ..storage.ask_history_store import AskHistoryStore
from ..storage.postgres_cross_session_store import PostgresCrossSessionStore
from ..storage.postgres_memory_store import PostgresMemoryStore
from ..storage.postgres_pending_action_store import PostgresPendingActionStore
from ..tools import ToolExecutor
from .orchestration_graph import _build_checkpointer, build_entry_orchestration_graph
from .orchestration_nodes import OrchestrationDeps
from .orchestration_models import AgentGraphState, AgentRunSnapshot, PlanStepState
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


def _snapshot_intent(snapshot: dict) -> str:
    """Extract intent string from a raw state snapshot dict.

    Handles three forms of ``router_decision`` in the snapshot:
    None (before routing), a dict (legacy checkpoints), or a RouterDecision instance.
    """
    rd = snapshot.get("router_decision")
    if rd is None:
        return "unknown"
    if isinstance(rd, dict):
        return str(rd.get("route", "unknown"))
    return str(getattr(rd, "route", "unknown"))


def _checkpoint_values_after_interrupt(graph, config: dict, fallback: object) -> dict:
    """Merge parent checkpoint state with streamed child state at an interrupt."""
    streamed_values = {
        key: value for key, value in fallback.items() if key != "__interrupt__"
    } if isinstance(fallback, dict) else {}
    try:
        values = graph.get_state(config).values
        if isinstance(values, dict):
            return {**values, **streamed_values}
    except Exception:
        logger.debug("Could not read state after graph interrupt", exc_info=True)
    return streamed_values


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
        store: PostgresMemoryStore,
        graph_store: GraphitiStore,
        ask_history_store: AskHistoryStore,
        capture_service: "CaptureService | None" = None,
        pending_action_store: PostgresPendingActionStore | None = None,
    ) -> None:
        if not settings.postgres_url:
            raise ValueError("PERSONAL_AGENT_POSTGRES_URL is required for business persistence.")
        self.settings = settings
        self.store = store
        self.graph_store = graph_store
        self.ask_history_store = ask_history_store
        self.pending_action_store = pending_action_store or PostgresPendingActionStore(settings.postgres_url)
        self.capture_service = capture_service
        self._intent_router = DefaultIntentRouter(settings)
        self._tool_executor = ToolExecutor()
        self._register_tools()
        self._planner = DefaultTaskPlanner(settings, tool_executor=self._tool_executor)
        self._cross_session = PostgresCrossSessionStore(settings.postgres_url)
        self.memory = MemoryFacade(store, ask_history_store, cross_session_store=self._cross_session)
        self._verifier = AnswerVerifier()
        self._plan_validator = PlanValidator(tool_executor=self._tool_executor)
        self._replanner = Replanner(settings)
        self._react_runner = ReActStepRunner(
            tool_executor=self._tool_executor,
            memory=self.memory,
            settings=settings,
        )
        self._thread_message_loader: (
            Callable[[EntryInput, int], list[dict[str, str]]] | None
        ) = None
        # Orchestration graph — built lazily on first use
        self._orch_graph = None

    # ---- public properties (delegate to private fields so test mocks are visible) ----

    @property
    def intent_router(self):
        return self._intent_router

    @property
    def tool_executor(self):
        return self._tool_executor

    @property
    def planner(self):
        return self._planner

    @property
    def plan_validator(self):
        return self._plan_validator

    def set_thread_message_loader(
        self, loader: Callable[[EntryInput, int], list[dict[str, str]]] | None
    ) -> None:
        """Register a platform adapter used only after the graph selects summary."""
        self._thread_message_loader = loader

    def load_thread_messages(
        self, entry_input: EntryInput, limit: int = 20
    ) -> list[dict[str, str]]:
        if self._thread_message_loader is None:
            return []
        return self._thread_message_loader(entry_input, limit)

    # ---- orchestration graph ----

    def _get_orch_graph(self):
        """Lazily build and cache the entry orchestration graph."""
        if self._orch_graph is None:
            checkpointer = _build_checkpointer(self.settings)
            deps = OrchestrationDeps.from_runtime(self)
            self._orch_graph = build_entry_orchestration_graph(deps, checkpointer=checkpointer)
            logger.info("Entry orchestration graph built with Postgres checkpoints")
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
        thread_id = _new_thread_id(normalized_user, normalized_session)

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

        # Pass explicit null/default values as channel updates. When a Pydantic
        # model is used directly, LangGraph omits nullable defaults while
        # resuming an existing thread, leaving prior-run transient values in
        # the input checkpoint until the first node resets them.
        invoke_result = self._stream_entry_graph(
            graph,
            initial_state.model_dump(),
            config,
            on_progress or (lambda _event_type, _payload: None),
        )
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            return self._entry_result_from_interrupt(
                _checkpoint_values_after_interrupt(graph, config, invoke_result),
                interrupt_data,
                run_id=run_id,
                thread_id=thread_id,
                fallback_events=(
                    invoke_result.get("events", initial_state.events)
                    if isinstance(invoke_result, dict)
                    else initial_state.events
                ),
            )

        result_state = AgentGraphState.model_validate(invoke_result)

        # Map graph state back to EntryResult for API compatibility
        reply_text = result_state.answer or "暂时没有可执行的结果。"

        capture_result = None
        ask_result = None
        if result_state.router_decision and result_state.router_decision.route in ("capture_text", "capture_link", "capture_file"):
            for item in reversed(result_state.tool_results):
                capture_payload = item.get("capture_result") if isinstance(item, dict) else None
                if isinstance(capture_payload, dict):
                    capture_result = CaptureResult.model_validate(capture_payload)
                    break
        elif result_state.router_decision and result_state.router_decision.route == "ask":
            ask_result = AskResult(
                answer=reply_text,
                citations=result_state.citations,
                matches=[],
                session_id=normalized_session,
            )

        return EntryResult(
            intent=result_state.router_decision.route if result_state.router_decision else "unknown",
            reason=result_state.router_decision.user_visible_message if result_state.router_decision else "未提供路由说明。",
            reply_text=reply_text,
            capture_result=capture_result,
            ask_result=ask_result,
            plan_steps=[s.model_dump(mode="json") for s in result_state.plan_steps],
            execution_trace=result_state.execution_trace,
            run_id=run_id,
            thread_id=thread_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in result_state.events],
        )

    def _stream_entry_graph(self, graph, initial_state: dict, config: dict, on_progress):
        """Run graph nodes while forwarding newly persisted events to a caller."""
        from .orchestration_models import AgentEvent, events_to_sse_tuples

        emitted_event_ids: set[str] = set()
        observed_events: list[AgentEvent] = []
        observed_state = dict(initial_state)
        interrupt_result: dict | None = None
        for streamed in graph.stream(initial_state, config, stream_mode="updates", subgraphs=True):
            update = (
                streamed[1]
                if isinstance(streamed, tuple)
                and len(streamed) == 2
                and isinstance(streamed[1], dict)
                else streamed
            )
            if not isinstance(update, dict):
                continue
            if "__interrupt__" in update:
                interrupt_result = update
            for node_update in update.values():
                if not isinstance(node_update, dict):
                    continue
                observed_state.update(node_update)
                for raw_event in node_update.get("events", []):
                    event = (
                        raw_event
                        if isinstance(raw_event, AgentEvent)
                        else AgentEvent.model_validate(raw_event)
                    )
                    if event.event_id in emitted_event_ids:
                        continue
                    emitted_event_ids.add(event.event_id)
                    observed_events.append(event)
                    for event_type, payload in events_to_sse_tuples([event]):
                        # The HTTP layer emits one terminal result with complete
                        # answer/citation metadata after graph completion.
                        if event_type != "done":
                            on_progress(event_type, payload)
        if interrupt_result is not None:
            return {
                **observed_state,
                "__interrupt__": interrupt_result["__interrupt__"],
                "events": observed_events or observed_state.get("events", []),
            }
        return graph.get_state(config).values

    def _entry_result_from_interrupt(
        self,
        invoke_result: object,
        interrupt_data: dict,
        *,
        run_id: str,
        thread_id: str,
        fallback_events: list | None = None,
    ) -> EntryResult:
        state_snapshot = invoke_result if isinstance(invoke_result, dict) else {}
        kind = str(interrupt_data.get("kind") or "")
        is_clarification = kind == "clarification_required"
        reason = "需要补充信息" if is_clarification else "操作需要用户确认"
        default_message = "请补充更多信息后继续。" if is_clarification else "此操作需要您的确认。"

        logger.info(
            "Graph interrupted run_id=%s thread_id=%s kind=%s step=%s",
            run_id, thread_id, kind or "confirmation", interrupt_data.get("step_id", "?"),
        )
        return EntryResult(
            intent=_snapshot_intent(state_snapshot),
            reason=reason,
            reply_text=str(interrupt_data.get("message", default_message)),
            plan_steps=[
                s.model_dump(mode="json") if isinstance(s, PlanStepState) else s
                for s in (state_snapshot.get("plan_steps") or [])
            ],
            execution_trace=list(state_snapshot.get("execution_trace") or []),
            run_id=run_id,
            thread_id=thread_id,
            pending_confirmation=interrupt_data,
            run_status="waiting_confirmation",
            events=[
                e.model_dump(mode="json") if hasattr(e, "model_dump") else e
                for e in (state_snapshot.get("events") or fallback_events or [])
            ],
        )

    def resume_entry(
        self, run_id: str, thread_id: str, decision: str, user_id: str,
        text: str | None = None, option_id: str | None = None,
    ) -> EntryResult:
        """Resume a graph run that was interrupted for HITL confirmation.

        Args:
            run_id: The run to resume.
            thread_id: Thread ID from the original run config.
            decision: ``"confirm"``, ``"reject"`` or ``"clarify"``.
            user_id: Authenticated user making the decision.
            text: Supplemental text for clarification interrupts.
            option_id: Optional clarification option selected by the user.

        Returns:
            Final EntryResult after graph completion.
        """
        graph = self._get_orch_graph()
        config = {"configurable": {"thread_id": thread_id}}
        resume_value = {
            "decision": decision,
            "user_id": user_id,
            "text": text or "",
            "option_id": option_id or "",
        }

        logger.info(
            "Resuming graph run_id=%s thread_id=%s decision=%s",
            run_id, thread_id, decision,
        )

        invoke_result = graph.invoke(Command(resume=resume_value), config)
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            return self._entry_result_from_interrupt(
                _checkpoint_values_after_interrupt(graph, config, invoke_result),
                interrupt_data,
                run_id=run_id,
                thread_id=thread_id,
            )

        result_state = AgentGraphState.model_validate(invoke_result)

        reply_text = result_state.answer or "操作已完成。"

        return EntryResult(
            intent=result_state.router_decision.route if result_state.router_decision else "unknown",
            reason=result_state.router_decision.user_visible_message if result_state.router_decision else "",
            reply_text=reply_text,
            plan_steps=[s.model_dump(mode="json") for s in result_state.plan_steps],
            execution_trace=result_state.execution_trace,
            run_id=run_id,
            thread_id=thread_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in result_state.events],
        )

    def get_run_snapshot(self, run_id: str) -> AgentRunSnapshot | None:
        """Return a read-only snapshot for the most recent checkpoint of a run."""
        try:
            checkpointer = self._get_orch_graph().checkpointer
            for ct in checkpointer.list(None, limit=500):
                if ct.checkpoint and "channel_values" in ct.checkpoint:
                    cv = ct.checkpoint["channel_values"]
                    state = AgentGraphState.model_validate(cv)
                    if state.run_id == run_id:
                        return state.to_run_snapshot()
        except Exception:
            logger.debug("Could not retrieve run snapshot for run_id=%s", run_id, exc_info=True)
        return None

    def list_run_snapshots(
        self, user_id: str | None = None, limit: int = 50,
    ) -> list[AgentRunSnapshot]:
        """List recent run snapshots, optionally filtered by user.

        Returns the most recent checkpoint per run_id. Multiple runs may share
        one LangGraph thread for a conversation session.
        """
        try:
            checkpointer = self._get_orch_graph().checkpointer
            newest_by_run: dict[str, AgentRunSnapshot] = {}
            for ct in checkpointer.list(None, limit=500):
                if ct.checkpoint and "channel_values" in ct.checkpoint:
                    cv = ct.checkpoint["channel_values"]
                    state = AgentGraphState.model_validate(cv)
                    if user_id and state.user_id != user_id:
                        continue
                    if state.run_id in newest_by_run:
                        continue
                    newest_by_run[state.run_id] = state.to_run_snapshot()
            snapshots = list(newest_by_run.values())
            snapshots.sort(key=lambda s: s.updated_at, reverse=True)
            return snapshots[:limit]
        except Exception:
            logger.debug("Could not list run snapshots", exc_info=True)
        return []

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
