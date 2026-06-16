"""Entry orchestration: graph lifecycle, execution, resume, and snapshots.

Extracted from ``AgentRuntime`` so the runtime is a thin composition root and
the LangGraph entry-graph wiring lives in one focused place. ``EntryOrchestrator``
holds a back-reference to the runtime (the composition root) purely to build
``OrchestrationDeps`` from its collaborators.
"""

from __future__ import annotations

import logging

from langgraph.types import Command

from ..core.langsmith_tracing import langsmith_trace_context
from ..core.models import EntryInput
from ..core.observability import RunMetrics
from .orchestration_graph import _build_checkpointer, build_entry_orchestration_graph
from .orchestration_nodes import OrchestrationDeps
from .orchestration_models import AgentGraphState, AgentRunSnapshot, StepRunState
from .runtime_results import AskResult, CaptureResult, EntryResult

logger = logging.getLogger(__name__)

CHECKPOINT_SCHEMA_VERSION = "step_execution_v2"
LEGACY_REPLAY_UPDATE_KEYS = {
    "plan",
    "plan" + "_steps",
    "requires" + "_planning",
    "plan" + "_created",
    "plan" + "_validated",
}
ALLOWED_REPLAY_UPDATE_KEYS = {
    "entry_input",
    "entry_text",
    "messages",
    "thread_summary",
    "router_decision",
    "react",
    "step_execution",
    "tool_tracking",
    "tool_messages",
    "tool_results",
    "execution_trace",
    "citations",
    "matches",
    "pending_confirmation",
    "confirmation_decision",
    "answer",
    "answer_completed",
    "events",
    "errors",
}


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


def _steps_from_snapshot(snapshot: dict) -> list:
    """Extract projected step list from a checkpoint snapshot."""
    step_execution = snapshot.get("step_execution")
    if isinstance(step_execution, dict) and "steps" in step_execution:
        return step_execution.get("steps") or []
    if step_execution is not None and hasattr(step_execution, "steps"):
        return getattr(step_execution, "steps") or []
    return []


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


def _checkpoint_id_from_config(config: dict | None) -> str | None:
    configurable = (config or {}).get("configurable") if isinstance(config, dict) else None
    if not isinstance(configurable, dict):
        return None
    checkpoint_id = configurable.get("checkpoint_id") or configurable.get("checkpoint_ns")
    return str(checkpoint_id) if checkpoint_id else None


def _step_execution_summary(state: AgentGraphState) -> dict[str, object]:
    statuses: dict[str, int] = {}
    for step in state.step_execution.steps:
        statuses[step.status] = statuses.get(step.status, 0) + 1
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "step_count": len(state.step_execution.steps),
        "current_step_index": state.step_execution.current_step_index,
        "aborted": state.step_execution.aborted,
        "result_keys": sorted(state.step_execution.results.keys()),
        "statuses": statuses,
    }


def _validate_replay_updates(updates: dict[str, object]) -> None:
    invalid = sorted(set(updates) - ALLOWED_REPLAY_UPDATE_KEYS)
    legacy = sorted(set(updates) & LEGACY_REPLAY_UPDATE_KEYS)
    if legacy:
        raise ValueError(
            "Replay updates use legacy checkpoint fields that are no longer supported: "
            + ", ".join(legacy)
            + ". Use step_execution-based fields."
        )
    if invalid:
        raise ValueError(
            "Replay updates contain unsupported fields: "
            + ", ".join(invalid)
            + ". Allowed fields are: "
            + ", ".join(sorted(ALLOWED_REPLAY_UPDATE_KEYS))
        )


def _ensure_checkpoint_schema_supported(values: dict[str, object], checkpoint_id: str) -> None:
    if "plan" in values:
        raise ValueError(
            f"Checkpoint {checkpoint_id} uses legacy plan schema and cannot be replayed. "
            "Clear or migrate old LangGraph checkpoints before using replay_from_checkpoint."
        )
    if "step_execution" not in values:
        raise ValueError(
            f"Checkpoint {checkpoint_id} does not contain step_execution state and cannot be replayed "
            f"as {CHECKPOINT_SCHEMA_VERSION}."
        )


def _snapshot_to_history_item(snapshot: object) -> dict[str, object] | None:
    values = getattr(snapshot, "values", None)
    if not isinstance(values, dict):
        return None
    try:
        state = AgentGraphState.model_validate(values)
    except Exception:
        return None
    config = getattr(snapshot, "config", None)
    metadata = getattr(snapshot, "metadata", None)
    created_at = getattr(snapshot, "created_at", None)
    parent_config = getattr(snapshot, "parent_config", None)
    return {
        "checkpoint_schema_version": CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_id": _checkpoint_id_from_config(config),
        "parent_checkpoint_id": _checkpoint_id_from_config(parent_config),
        "thread_id": state.thread_id,
        "run_id": state.run_id,
        "user_id": state.user_id,
        "session_id": state.session_id,
        "status": state.to_run_snapshot().status.value,
        "intent": state.router_decision.route if state.router_decision else "unknown",
        "next": list(getattr(snapshot, "next", ()) or ()),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else None,
        "updated_at": state.updated_at.isoformat() if state.updated_at else None,
        "event_count": len(state.events),
        "tool_result_count": len(state.tool_results),
        "step_execution": _step_execution_summary(state),
        "answer_completed": state.answer_completed,
        "pending_confirmation": state.pending_confirmation,
    }


def _entry_trace_metadata(
    *,
    run_id: str,
    thread_id: str,
    user_id: str,
    session_id: str,
    entry_input: EntryInput,
) -> dict[str, object]:
    return {
        "app": "personal-agent",
        "run_id": run_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "session_id": session_id,
        "source_platform": entry_input.source_platform or "unknown",
        "source_type": entry_input.source_type,
        "has_source_ref": bool(entry_input.source_ref),
    }


def _graph_checkpointer_closed(graph) -> bool:
    checkpointer = getattr(graph, "checkpointer", None)
    conn = getattr(checkpointer, "conn", None)
    return bool(getattr(conn, "closed", False))


class EntryOrchestrator:
    """Owns the LangGraph entry graph and the execute / resume / snapshot flow.

    Holds a back-reference to the runtime composition root so it can build
    ``OrchestrationDeps`` from the runtime's collaborators, and caches the
    compiled graph (rebuilding if the checkpointer connection drops).
    """

    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._orch_graph = None

    @property
    def settings(self):
        return self._runtime.settings

    def _get_orch_graph(self):
        """Lazily build and cache the entry orchestration graph."""
        if self._orch_graph is not None and _graph_checkpointer_closed(self._orch_graph):
            logger.warning("Cached orchestration graph checkpointer connection is closed; rebuilding graph")
            self._orch_graph = None
        if self._orch_graph is None:
            checkpointer = _build_checkpointer(self.settings)
            deps = OrchestrationDeps.from_runtime(self._runtime)
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

        metadata = _entry_trace_metadata(
            run_id=run_id,
            thread_id=thread_id,
            user_id=normalized_user,
            session_id=normalized_session,
            entry_input=entry_input,
        )
        # Name the LangGraph root run and attach business metadata so the whole
        # node/LLM/tool subtree hangs off one searchable "execute_entry" run.
        config["run_name"] = "execute_entry"
        config["metadata"] = dict(metadata)
        config["tags"] = ["entry", f"source:{metadata['source_platform']}"]
        run_metrics = RunMetrics(
            run_id=run_id,
            thread_id=thread_id,
            user_id=normalized_user,
            session_id=normalized_session,
        )

        # Pass explicit null/default values as channel updates. When a Pydantic
        # model is used directly, LangGraph omits nullable defaults while
        # resuming an existing thread, leaving prior-run transient values in
        # the input checkpoint until the first node resets them.
        try:
            with langsmith_trace_context(
                self.settings.langsmith,
                metadata=metadata,
                tags=["entry", f"source:{metadata['source_platform']}"],
            ):
                invoke_result = self._stream_entry_graph(
                    graph,
                    initial_state.model_dump(),
                    config,
                    on_progress or (lambda _event_type, _payload: None),
                )
        except Exception as exc:
            run_metrics.complete(status="failed", error_type=exc.__class__.__name__)
            raise
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            run_metrics.complete(status="waiting_confirmation", interrupt_kind=interrupt_data.get("kind"))
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
            # Full KnowledgeNote matches are not checkpointed onto the state
            # (only summary dicts, to avoid checkpoint bloat). Surface them as
            # lightweight MatchRefs so result matching / citation validation see
            # the matches instead of an empty list.
            from ..core.projections import MatchRef

            match_refs = [
                MatchRef(id=str(m.get("id", "")), title=str(m.get("title", "")))
                for m in (result_state.matches or [])
                if isinstance(m, dict) and m.get("id")
            ]
            ask_result = AskResult(
                answer=reply_text,
                citations=result_state.citations,
                matches=[],
                match_refs=match_refs,
                session_id=normalized_session,
            )

        intent = result_state.router_decision.route if result_state.router_decision else "unknown"
        run_metrics.intent = intent
        run_metrics.complete(
            status="completed",
            step_count=len(result_state.step_execution.steps),
            tool_result_count=len(result_state.tool_results),
            event_count=len(result_state.events),
        )
        return EntryResult(
            intent=intent,
            reason=result_state.router_decision.user_visible_message if result_state.router_decision else "未提供路由说明。",
            reply_text=reply_text,
            capture_result=capture_result,
            ask_result=ask_result,
            steps=[s.model_dump(mode="json") for s in result_state.step_execution.steps],
            execution_trace=result_state.execution_trace,
            applied_reflection_ids=list(result_state.applied_reflection_ids),
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
            steps=[
                s.model_dump(mode="json") if isinstance(s, StepRunState) else s
                for s in (_steps_from_snapshot(state_snapshot))
            ],
            execution_trace=list(state_snapshot.get("execution_trace") or []),
            applied_reflection_ids=list(state_snapshot.get("applied_reflection_ids") or []),
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
        config = {
            "configurable": {"thread_id": thread_id},
            "run_name": "resume_entry",
            "metadata": {
                "app": "personal-agent",
                "run_id": run_id,
                "thread_id": thread_id,
                "user_id": user_id,
                "resume_decision": decision,
            },
            "tags": ["entry", "resume"],
        }
        resume_value = {
            "decision": decision,
            "user_id": user_id,
            "text": text or "",
            "option_id": option_id or "",
        }
        run_metrics = RunMetrics(
            run_id=run_id,
            thread_id=thread_id,
            user_id=user_id,
        )

        logger.info(
            "Resuming graph run_id=%s thread_id=%s decision=%s",
            run_id, thread_id, decision,
        )

        try:
            with langsmith_trace_context(
                self.settings.langsmith,
                metadata={
                    "app": "personal-agent",
                    "run_id": run_id,
                    "thread_id": thread_id,
                    "user_id": user_id,
                    "resume_decision": decision,
                },
                tags=["entry", "resume"],
            ):
                invoke_result = graph.invoke(Command(resume=resume_value), config)
        except Exception as exc:
            run_metrics.complete(
                status="failed",
                resume_decision=decision,
                error_type=exc.__class__.__name__,
            )
            raise
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            run_metrics.complete(
                status="waiting_confirmation",
                resume_decision=decision,
                interrupt_kind=interrupt_data.get("kind"),
            )
            return self._entry_result_from_interrupt(
                _checkpoint_values_after_interrupt(graph, config, invoke_result),
                interrupt_data,
                run_id=run_id,
                thread_id=thread_id,
            )

        result_state = AgentGraphState.model_validate(invoke_result)

        reply_text = result_state.answer or "操作已完成。"
        intent = result_state.router_decision.route if result_state.router_decision else "unknown"
        run_metrics.intent = intent
        run_metrics.session_id = result_state.session_id
        run_metrics.complete(
            status="completed",
            resume_decision=decision,
            step_count=len(result_state.step_execution.steps),
            tool_result_count=len(result_state.tool_results),
            event_count=len(result_state.events),
        )

        return EntryResult(
            intent=intent,
            reason=result_state.router_decision.user_visible_message if result_state.router_decision else "",
            reply_text=reply_text,
            steps=[s.model_dump(mode="json") for s in result_state.step_execution.steps],
            execution_trace=result_state.execution_trace,
            applied_reflection_ids=list(result_state.applied_reflection_ids),
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

    def list_run_history(self, run_id: str, *, limit: int = 100) -> list[dict[str, object]]:
        """Return checkpoint history for one run using LangGraph state history."""
        if not run_id.strip():
            return []
        try:
            latest = self.get_run_snapshot(run_id)
            if latest is None:
                return []
            graph = self._get_orch_graph()
            config = {"configurable": {"thread_id": latest.thread_id}}
            items: list[dict[str, object]] = []
            for snapshot in graph.get_state_history(config, limit=max(1, limit)):
                item = _snapshot_to_history_item(snapshot)
                if item is None or item.get("run_id") != run_id:
                    continue
                items.append(item)
            return items
        except Exception:
            logger.debug("Could not list run history for run_id=%s", run_id, exc_info=True)
        return []

    def replay_from_checkpoint(
        self,
        *,
        thread_id: str,
        checkpoint_id: str,
        updates: dict[str, object],
        as_node: str | None = None,
    ) -> EntryResult:
        """Fork a historical checkpoint, apply state updates, and continue execution."""
        graph = self._get_orch_graph()
        config: dict[str, object] = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            },
            "run_name": "replay_entry",
            "metadata": {
                "app": "personal-agent",
                "thread_id": thread_id,
                "source_checkpoint_id": checkpoint_id,
                "time_travel": True,
            },
            "tags": ["entry", "replay"],
        }
        _validate_replay_updates(updates)
        source_state = graph.get_state(config)
        source_values = getattr(source_state, "values", None)
        if not isinstance(source_values, dict):
            raise ValueError(f"Checkpoint {checkpoint_id} could not be read for replay.")
        _ensure_checkpoint_schema_supported(source_values, checkpoint_id)
        update_kwargs = {"as_node": as_node} if as_node else {}
        fork_config = graph.update_state(config, updates, **update_kwargs)
        invoke_result = graph.invoke(None, fork_config)
        interrupt_data = _interrupt_payload_from_result(invoke_result)
        if interrupt_data is not None:
            values = _checkpoint_values_after_interrupt(graph, fork_config, invoke_result)
            run_id = str(values.get("run_id") or "")
            return self._entry_result_from_interrupt(
                values,
                interrupt_data,
                run_id=run_id,
                thread_id=thread_id,
            )

        result_state = AgentGraphState.model_validate(invoke_result)
        intent = result_state.router_decision.route if result_state.router_decision else "unknown"
        return EntryResult(
            intent=intent,
            reason=result_state.router_decision.user_visible_message if result_state.router_decision else "",
            reply_text=result_state.answer or "回放已完成。",
            steps=[s.model_dump(mode="json") for s in result_state.step_execution.steps],
            execution_trace=result_state.execution_trace,
            applied_reflection_ids=list(result_state.applied_reflection_ids),
            run_id=result_state.run_id,
            thread_id=result_state.thread_id,
            run_status="completed",
            events=[e.model_dump(mode="json") for e in result_state.events],
        )
