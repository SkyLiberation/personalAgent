"""Entry processing nodes: normalize, analyze, clarify, and finalize."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from personal_agent.kernel.models import EntryInput, local_now
from personal_agent.runtime.contracts.task import ContextInventory
from personal_agent.runtime.contracts.intake import TaskIntakeState
from personal_agent.kernel.contracts.interaction import InteractionOption, InteractionRequest
from personal_agent.governance.guardrails import get_content_guard
from personal_agent.orchestration.orchestration_models import (
    RunCheckpoint,
    InvocationBatchState,
    ReactSubState,
    ToolTrackingSubState,
    _new_run_id,
    _new_thread_id,
)
from personal_agent.orchestration.orchestration_contexts import ConversationContext, RoutingContext
from personal_agent.orchestration.orchestration_nodes._helpers import (
    _clarification_payload_parts,
    _dialogue_prompt_messages,
    _merge_clarification_text,
    _resume_value_get,
)

logger = logging.getLogger(__name__)

def _node_normalize_entry(state: RunCheckpoint) -> dict:
    if state.run_id is None or state.run_id == "":
        state.run_id = _new_run_id()

    entry = state.entry_input
    user_id = entry.user_id if entry else state.user_id
    session_id = entry.session_id if entry else state.session_id
    text = entry.text if entry else state.entry_text

    input_guard = get_content_guard().check_input(text or "")
    text = input_guard.text

    thread_id = _new_thread_id(user_id, session_id)

    state.user_id = user_id
    state.session_id = session_id
    state.thread_id = thread_id
    state.entry_text = text
    state.intake = TaskIntakeState(
        original_input_ref=f"entry:{state.run_id}",
        source_message_refs=(f"{state.run_id}:user",),
    )
    state.task_analysis = None
    state.task_contract = None
    state.task_runtime = None
    state.context_inventory = ContextInventory()
    state.active_procedure = None
    state.control.state = None
    state.control.proposal = None
    state.decision_admission = None
    state.control.accepted_command = None
    state.control.actions = []
    state.control.action_outcome = None
    state.control.observations = []
    state.verification_reports = {}
    state.completion_report = None
    state.execution_events = []
    state.execution_grants = {}
    from personal_agent.execution.contracts.journal import InvocationJournalProjection
    state.invocation_journal = InvocationJournalProjection()
    from personal_agent.capabilities.contracts.acquisition import CapabilityAcquisitionProjection
    state.capability_acquisition = CapabilityAcquisitionProjection()
    state.evidence_admissions = {}
    state.capability_execution_outcomes = []
    state.capability_effectiveness_outcomes = []
    state.task_compilation_commit = None
    state.control_commits = []
    state.control.turn_index = 0
    state.control.last_decision_hash = ""
    state.control.repeated_decision_count = 0
    state.control.phase = "preparing_model_call"
    state.control.disposition = "continue_control"
    state.context_projections = []
    state.control.resolved_actions = []
    state.control.retry_directive = None
    state.react = ReactSubState()
    state.invocation_batch = InvocationBatchState()
    state.tool_tracking = ToolTrackingSubState()
    state.tool_results = []
    state.provider_call_count = 0
    state.tool_messages = []
    state.citations = []
    state.matches = []
    state.control.pending_interaction = None
    state.control.interaction_decision = None
    state.control.confirmed_invocation_id = None
    state.answer = None
    state.events = []
    state.errors = []
    state.created_at = local_now()
    state.updated_at = state.created_at

    if input_guard.changed:
        state.add_event(
            "guardrail_blocked" if input_guard.blocked else "guardrail_sanitized",
            {
                "stage": "input",
                "categories": list(input_guard.categories),
                "reason": input_guard.reason,
            },
        )
    state.add_event("entry_started", {"text_preview": text[:120] if text else ""})
    logger.info("normalize_entry run_id=%s thread_id=%s", state.run_id, thread_id)
    return {
        "user_id": user_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "entry_text": text,
        "messages": [HumanMessage(content=text, id=f"{state.run_id}:user")],
        "tool_messages": [],
        "task_analysis": None,
        "intake": state.intake,
        "task_contract": None,
        "task_runtime": None,
        "context_inventory": state.context_inventory,
        "active_procedure": None,
        "control": state.control,
        "decision_admission": None,
        "verification_reports": {},
        "completion_report": None,
        "execution_events": [],
        "execution_grants": {},
        "invocation_journal": state.invocation_journal,
        "capability_acquisition": state.capability_acquisition,
        "evidence_admissions": {},
        "capability_execution_outcomes": [],
        "capability_effectiveness_outcomes": [],
        "task_compilation_commit": None,
        "control_commits": [],
        "context_projections": [],
        "react": state.react,
        "invocation_batch": state.invocation_batch,
        "tool_tracking": state.tool_tracking,
        "tool_results": [],
        "provider_call_count": 0,
        "citations": [],
        "matches": [],
        "answer": None,
        "events": state.events,
        "errors": [],
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _node_prepare_clarify(state: RunCheckpoint) -> dict:
    """Materialize a TaskAnalyzer clarification before interrupting.

    ``analyze_task`` has already determined that information is missing. This
    node writes the payload first so the checkpoint records exactly what the
    UI should present before ``interrupt()`` pauses execution.
    """
    decision = state.task_analysis
    if decision is None or not decision.requires_clarification:
        return {}

    issue = _clarification_payload_parts(
        decision.clarification_prompt
        or "请补充你想记录、查询、总结或执行的具体内容。",
        "入口信息不足，需要用户补充。",
    )
    payload = InteractionRequest(
        kind="clarification_required",
        action_type="clarify_entry",
        step_id="clarify_entry",
        title="需要补充信息",
        message=issue["message"],
        summary=issue["summary"],
        original_text=state.entry_text,
        missing_information=tuple(decision.missing_information),
        options=tuple(
            InteractionOption(
                option_id=str(option["id"]),
                label=str(option["label"]),
                description=str(option["prompt"]),
            )
            for option in issue["options"]
        ),
    )
    state.control.pending_interaction = payload
    event = state.add_event("clarification_required", payload.model_dump(mode="json"))
    if state.intake is None:
        raise RuntimeError("clarification requires intake state")
    state.intake = state.intake.model_copy(update={
        "status": "awaiting_input",
        "interaction_request_ref": event.event_id,
    })
    return {"intake": state.intake, "control": state.control, "events": state.events}


def _node_interrupt_clarify(state: RunCheckpoint) -> dict:
    """Pause the graph for human clarification and process the resume value.

    Expects ``state.control.pending_interaction`` to be populated by the upstream
    ``_node_prepare_clarify`` node (and therefore present in the checkpoint).
    """
    payload = state.control.pending_interaction
    if payload is None:
        return {}

    resume_value = interrupt(payload.model_dump(mode="json"))
    decision = str(_resume_value_get(resume_value, "decision", "clarify")).lower()
    if decision in ("reject", "cancel"):
        state.control.pending_interaction = None
        state.answer = "已取消。你可以重新发送更完整的内容。"
        state.add_event("answer_completed", {"reason": "clarification_cancelled"})
        state.add_event("clarification_resumed", {"decision": "cancelled"})
        if state.intake is not None:
            state.intake = state.intake.model_copy(update={
                "status": "cancelled",
                "interaction_request_ref": None,
            })
        return {
            "intake": state.intake,
            "control": state.control,
            "answer": state.answer,
            "events": state.events,
        }

    supplemental = str(_resume_value_get(resume_value, "text", "")).strip()
    option_id = str(_resume_value_get(resume_value, "option_id", "")).strip()
    if not supplemental:
        state.control.pending_interaction = None
        state.answer = "还需要补充具体内容后才能继续。请重新发起请求，并说明要记录、查询、总结或执行什么。"
        state.add_event("answer_completed", {"reason": "clarification_empty"})
        state.add_event("clarification_resumed", {"decision": "empty"})
        if state.intake is not None:
            state.intake = state.intake.model_copy(update={
                "status": "cancelled",
                "interaction_request_ref": None,
            })
        return {
            "intake": state.intake,
            "control": state.control,
            "answer": state.answer,
            "events": state.events,
        }

    clarified_text = _merge_clarification_text(state.entry_text, supplemental, option_id)
    state.entry_text = clarified_text
    if state.entry_input is not None:
        state.entry_input = state.entry_input.model_copy(update={"text": clarified_text})
    else:
        state.entry_input = EntryInput(
            text=clarified_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )
    state.add_event("clarification_resumed", {
        "decision": "clarified",
        "option_id": option_id,
        "text_preview": clarified_text[:120],
    })
    state.task_analysis = None
    state.control.pending_interaction = None
    if state.intake is not None:
        state.intake = state.intake.model_copy(update={
            "status": "analyzing",
            "interaction_request_ref": None,
        })
    return {
        "entry_text": clarified_text,
        "entry_input": state.entry_input,
        "messages": [HumanMessage(content=supplemental, id=f"{state.run_id}:clarification")],
        "control": state.control,
        "intake": state.intake,
        "task_analysis": None,
        "events": state.events,
    }


def _after_prepare_clarify(state: RunCheckpoint) -> str:
    """Route to interrupt after its payload has been checkpointed."""
    if state.control.pending_interaction is not None:
        return "interrupt_clarify_entry"
    return "analyze_task"


def _after_interrupt_clarify(state: RunCheckpoint) -> str:
    """After interrupt, finalize if cancelled/empty; otherwise analyze the enriched task."""
    if state.answer_completed:
        return "finalize_entry_result"
    return "analyze_task"


# ============================================================================
def _node_analyze_task(state: RunCheckpoint, *, deps: RoutingContext) -> dict:
    """Bind conversation context and produce semantic task understanding."""
    from personal_agent.kernel.logging_utils import log_event as _log_event

    if state.entry_input is None:
        state.entry_input = EntryInput(
            text=state.entry_text,
            user_id=state.user_id,
            session_id=state.session_id,
        )

    deps.memory.bind_session(state.user_id, state.session_id)
    conversation_messages = _entry_conversation_messages(state, exclude_latest=True, deps=deps)
    supplied_analysis = (state.entry_input.metadata or {}).get("task_analysis")
    trusted_internal_entry = state.entry_input.source_platform in {"worker", "runtime"}
    if trusted_internal_entry and isinstance(supplied_analysis, dict):
        from personal_agent.planning.task_analyzer import TaskAnalysis

        decision = TaskAnalysis.model_validate(supplied_analysis)
    else:
        decision = deps.task_analyzer.analyze(
            state.entry_input,
            conversation_messages=conversation_messages,
        )

    state.task_analysis = decision
    if decision.outcome == "rejected":
        state.answer = decision.rejection_reason
        state.add_event("answer_completed", {"reason": "task_rejected"})
    state.invocation_batch.invocations = []

    event = state.add_event("task_analyzed", {
        "result_contracts": [goal.result_contract for goal in decision.goals],
        "goals": [goal.model_dump(mode="json") for goal in decision.goals],
        "relations": [item.model_dump(mode="json") for item in decision.relations],
        "reason": _analysis_reason(decision),
        "requires_clarification": decision.requires_clarification,
        "outcome": decision.outcome,
    })
    if state.intake is None:
        raise RuntimeError("task analysis requires intake state")
    state.intake = state.intake.model_copy(update={
        "status": "cancelled" if decision.outcome == "rejected" else "analyzing",
        "current_proposal_ref": event.event_id,
        "proposal_revision": state.intake.proposal_revision + 1,
        "missing_requirement_ids": tuple(decision.missing_information),
        "interaction_request_ref": None,
    })

    _log_event(
        logger,
        logging.INFO,
        "entry.task_analysis",
        user_id=state.user_id,
        session_id=state.session_id,
        result_contracts=[goal.result_contract for goal in decision.goals],
        requires_clarification=decision.requires_clarification,
        reason=_analysis_reason(decision),
    )

    logger.info(
        "analyze_task run_id=%s goals=%s requires_clarification=%s",
        state.run_id, [goal.goal_id for goal in decision.goals], decision.requires_clarification,
    )

    return {
        "task_analysis": state.task_analysis,
        "intake": state.intake,
        "answer": state.answer,
        "invocation_batch": state.invocation_batch,
        "events": state.events,
    }


def _primary_result_contract(decision) -> str:
    return decision.goals[-1].result_contract if decision is not None and decision.goals else "unknown"


def _entry_conversation_messages(
    state: RunCheckpoint,
    *,
    exclude_latest: bool = True,
    deps: "RoutingContext | ConversationContext | None" = None,
) -> list[dict[str, str]]:
    """Return structured thread dialogue from checkpoint messages.

    When ``deps`` is provided, applies the unified short-term策略 (token 预算 +
    单条截断 + 溢出滚动摘要)；否则回退到默认窗口（无摘要）。
    """
    from personal_agent.kernel.config import ShortTermMemoryConfig
    from personal_agent.memory.short_term_context import build_dialogue_context_result

    if deps is None:
        return _dialogue_prompt_messages(state.messages, exclude_latest=exclude_latest)

    cfg = getattr(deps.settings, "short_term", None) or ShortTermMemoryConfig()
    summarizer = None
    if deps.compress_context is not None:
        user_id = state.user_id or "default"

        def summarizer(text: str) -> str:
            return deps.compress_context(text, user_id)

    result = build_dialogue_context_result(
        state.messages,
        cfg,
        exclude_latest=exclude_latest,
        prior_summary=state.thread_summary,
        summarizer=summarizer,
    )
    if result.summary_updated:
        state.thread_summary = result.thread_summary
    return result.messages


def _analysis_reason(decision) -> str:
    from personal_agent.planning.task_analyzer import describe_task_analysis

    return describe_task_analysis(decision)


def _node_finalize_entry_result(state: RunCheckpoint) -> dict:
    if (
        state.task_runtime is not None
        and state.task_runtime.lifecycle not in {"completed", "stopped"}
        and not state.answer_completed
    ):
        state.errors.append("completion_verifier_did_not_accept_task")
    if state.errors:
        state.add_event("run_failed", {"errors": state.errors})
    else:
        if state.answer:
            output_guard = get_content_guard().check_output(state.answer)
            if output_guard.changed:
                state.answer = output_guard.text
                state.add_event(
                    "guardrail_sanitized",
                    {
                        "stage": "output",
                        "categories": list(output_guard.categories),
                        "reason": output_guard.reason,
                    },
                )
        if not any(event.type == "answer_completed" for event in state.events):
            state.add_event("answer_completed", {"answer": state.answer})
        state.add_event("run_completed", {
            "answer": state.answer,
            "result_contracts": [goal.result_contract for goal in state.task_analysis.goals] if state.task_analysis else [],
        })
        logger.info(
            "finalize_entry_result relies on checkpoint messages run_id=%s intent=%s answer_len=%d",
            state.run_id,
            _primary_result_contract(state.task_analysis),
            len(state.answer or ""),
        )
    logger.info(
        "finalize_entry_result run_id=%s intent=%s errors=%d",
        state.run_id, _primary_result_contract(state.task_analysis), len(state.errors),
    )
    result = {
        "events": state.events,
        "updated_at": state.updated_at,
    }
    if not state.errors and state.answer:
        result["messages"] = [
            AIMessage(content=state.answer, id=f"{state.run_id}:assistant")
        ]
    return result
