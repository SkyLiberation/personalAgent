"""Entry processing nodes: normalize, analyze, clarify, and finalize."""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt

from personal_agent.kernel.models import EntryInput, local_now
from personal_agent.kernel.contracts.agentic import ContextEnvelope
from personal_agent.governance.guardrails import get_content_guard
from personal_agent.orchestration.orchestration_models import (
    AgentGraphState,
    StepExecutionState,
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

def _node_normalize_entry(state: AgentGraphState) -> dict:
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
    state.task_analysis = None
    state.task_spec = None
    state.execution_ledger = None
    state.context_envelope = ContextEnvelope()
    state.procedure_id = ""
    state.procedure_version = ""
    state.active_procedure = None
    state.control_state = None
    state.control_decision = None
    state.current_action = None
    state.current_actions = []
    state.current_action_outcome = None
    state.latest_observations = []
    state.completion_report = None
    state.execution_events = []
    state.executive_turn = 0
    state.last_decision_hash = ""
    state.repeated_decision_count = 0
    state.control_route = ""
    state.context_projections = []
    state.planning_model_context = {}
    state.control_model_context = {}
    state.resolved_action_spec = None
    state.resolved_action_specs = []
    state.retry_directive = None
    state.react = ReactSubState()
    state.step_execution = StepExecutionState()
    state.tool_tracking = ToolTrackingSubState()
    state.tool_results = []
    state.provider_call_count = 0
    state.tool_messages = []
    state.execution_trace = []
    state.citations = []
    state.matches = []
    state.pending_confirmation = None
    state.confirmation_decision = None
    state.confirmed_step_id = ""
    state.answer = None
    state.answer_completed = False
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
        "task_spec": None,
        "execution_ledger": None,
        "context_envelope": state.context_envelope,
        "procedure_id": "",
        "procedure_version": "",
        "active_procedure": None,
        "control_state": None,
        "control_decision": None,
        "current_action": None,
        "current_actions": [],
        "current_action_outcome": None,
        "latest_observations": [],
        "completion_report": None,
        "execution_events": [],
        "executive_turn": 0,
        "last_decision_hash": "",
        "repeated_decision_count": 0,
        "control_route": "",
        "context_projections": [],
        "planning_model_context": {},
        "control_model_context": {},
        "resolved_action_spec": None,
        "resolved_action_specs": [],
        "retry_directive": None,
        "react": state.react,
        "step_execution": state.step_execution,
        "tool_tracking": state.tool_tracking,
        "tool_results": [],
        "provider_call_count": 0,
        "execution_trace": [],
        "citations": [],
        "matches": [],
        "pending_confirmation": None,
        "confirmation_decision": None,
        "confirmed_step_id": "",
        "answer": None,
        "answer_completed": False,
        "events": state.events,
        "errors": [],
        "created_at": state.created_at,
        "updated_at": state.updated_at,
    }


def _node_prepare_clarify(state: AgentGraphState) -> dict:
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
    payload = {
        "kind": "clarification_required",
        "action_type": "clarify_entry",
        "step_id": "clarify_entry",
        "title": "需要补充信息",
        "message": issue["message"],
        "summary": issue["summary"],
        "original_text": state.entry_text,
        "missing_information": decision.missing_information,
        "options": issue["options"],
    }
    state.add_event("clarification_required", payload)
    return {"pending_confirmation": payload, "events": state.events}


def _node_interrupt_clarify(state: AgentGraphState) -> dict:
    """Pause the graph for human clarification and process the resume value.

    Expects ``state.pending_confirmation`` to be populated by the upstream
    ``_node_prepare_clarify`` node (and therefore present in the checkpoint).
    """
    payload = state.pending_confirmation
    if payload is None:
        return {}

    resume_value = interrupt(payload)
    decision = str(_resume_value_get(resume_value, "decision", "clarify")).lower()
    if decision in ("reject", "cancel"):
        state.answer = "已取消。你可以重新发送更完整的内容。"
        state.answer_completed = True
        state.execution_trace = ["用户取消补充信息，流程结束"]
        state.add_event("clarification_resumed", {"decision": "cancelled"})
        return {
            "pending_confirmation": None,
            "answer": state.answer,
            "answer_completed": True,
            "execution_trace": state.execution_trace,
            "events": state.events,
        }

    supplemental = str(_resume_value_get(resume_value, "text", "")).strip()
    option_id = str(_resume_value_get(resume_value, "option_id", "")).strip()
    if not supplemental:
        state.answer = "还需要补充具体内容后才能继续。请重新发起请求，并说明要记录、查询、总结或执行什么。"
        state.answer_completed = True
        state.execution_trace = ["补充信息为空，流程结束"]
        state.add_event("clarification_resumed", {"decision": "empty"})
        return {
            "pending_confirmation": None,
            "answer": state.answer,
            "answer_completed": True,
            "execution_trace": state.execution_trace,
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
    return {
        "entry_text": clarified_text,
        "entry_input": state.entry_input,
        "messages": [HumanMessage(content=supplemental, id=f"{state.run_id}:clarification")],
        "pending_confirmation": None,
        "task_analysis": None,
        "events": state.events,
    }


def _after_prepare_clarify(state: AgentGraphState) -> str:
    """Route to interrupt after its payload has been checkpointed."""
    if state.pending_confirmation is not None:
        return "interrupt_clarify_entry"
    return "analyze_task"


def _after_interrupt_clarify(state: AgentGraphState) -> str:
    """After interrupt, finalize if cancelled/empty; otherwise analyze the enriched task."""
    if state.answer_completed:
        return "finalize_entry_result"
    return "analyze_task"


# ============================================================================
def _node_analyze_task(state: AgentGraphState, *, deps: RoutingContext) -> dict:
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
        state.answer_completed = True
    state.step_execution.steps = []
    state.execution_trace = []

    state.add_event("task_analyzed", {
        "result_contracts": [goal.result_contract for goal in decision.goals],
        "goals": [goal.model_dump(mode="json") for goal in decision.goals],
        "relations": [item.model_dump(mode="json") for item in decision.relations],
        "reason": _analysis_reason(decision),
        "requires_clarification": decision.requires_clarification,
        "outcome": decision.outcome,
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
        "answer": state.answer,
        "answer_completed": state.answer_completed,
        "step_execution": state.step_execution,
        "execution_trace": [],
        "events": state.events,
    }


def _primary_result_contract(decision) -> str:
    return decision.goals[-1].result_contract if decision is not None and decision.goals else "unknown"


def _entry_conversation_messages(
    state: AgentGraphState,
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


def _node_finalize_entry_result(state: AgentGraphState) -> dict:
    from personal_agent.orchestration.orchestration_models import execution_trace_from_events

    if (
        state.task_spec is not None
        and state.task_spec.lifecycle not in {"completed", "stopped"}
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
        state.answer_completed = True
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
    state.execution_trace = execution_trace_from_events(state.events)
    result = {
        "answer_completed": state.answer_completed,
        "execution_trace": state.execution_trace,
        "events": state.events,
        "updated_at": state.updated_at,
    }
    if not state.errors and state.answer:
        result["messages"] = [
            AIMessage(content=state.answer, id=f"{state.run_id}:assistant")
        ]
    return result
