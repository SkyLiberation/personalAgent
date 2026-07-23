"""Entry processing nodes: normalize, analyze, clarify, and finalize."""

from __future__ import annotations

import json
import logging

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field

from personal_agent.kernel.models import EntryInput, local_now
from personal_agent.runtime.contracts.task import (
    ContextBudget,
    ContextInventory,
    ContextItem,
    RuntimeSnapshotRef,
)
from personal_agent.runtime.contracts.intake import TaskIntakeState
from personal_agent.kernel.contracts.interaction import InteractionOption, InteractionRequest
from personal_agent.governance.guardrails import get_content_guard
from personal_agent.verification.output_admission import FinalAnswerAdmission
from personal_agent.orchestration.orchestration_models import (
    RunCheckpoint,
    InvocationBatchState,
    ReactSubState,
    ToolTrackingSubState,
    _new_run_id,
    _new_thread_id,
)
from personal_agent.orchestration.orchestration_contexts import (
    ConversationContext,
    RoutingContext,
    StepExecutionContext,
)
from personal_agent.runtime.contracts.control import FinalAnswerProposal
from personal_agent.orchestration.orchestration_nodes._helpers import (
    _clarification_payload_parts,
    _dialogue_prompt_messages,
    _merge_clarification_text,
    _resume_value_get,
)

logger = logging.getLogger(__name__)


class _FinalAnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    citation_refs: tuple[str, ...] = ()


class _FinalAnswerWithoutCitations(BaseModel):
    """Model contract when the completed task exposes no citation identities.

    Citation absence is a closed-world fact from the final composition
    projection. Selecting this narrower contract cannot alter the business
    answer; it only makes an invalid citation field unrepresentable.
    """

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)

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
    state.task_analysis_attempts = []
    state.accepted_task_analysis = None
    state.task_contract = None
    state.task_runtime = None
    state.context_inventory = ContextInventory()
    state.active_procedure = None
    state.control.state = None
    state.control.proposal = None
    state.decision_admission = None
    state.decision_feedback = []
    state.decision_audit = []
    state.control.accepted_intent = None
    state.control.resolved_command = None
    state.control.actions = []
    state.control.action_outcome = None
    state.control.observations = []
    state.execution_fact_reports = {}
    state.verification_reports = {}
    state.verification_feedback = {}
    state.completion_report = None
    state.final_answer_proposal = None
    state.final_answer_admission = None
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
    state.control.last_intent_semantic_hash = ""
    state.control.last_submission_hash = ""
    state.control.seen_decision_cycle_keys = ()
    state.control.active_revision_lineage_id = None
    state.control.active_feedback_ref = None
    state.control.revision_attempt = 0
    state.control.cross_stage_revision_cycles = 0
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
        "task_analysis_attempts": [],
        "accepted_task_analysis": None,
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
    accepted = state.accepted_task_analysis
    decision = accepted.analysis if accepted is not None else None
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
    state.task_analysis_attempts = []
    state.accepted_task_analysis = None
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
        "task_analysis_attempts": [],
        "accepted_task_analysis": None,
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
    result = deps.task_analyzer.analyze(
        state.entry_input,
        conversation_messages=conversation_messages,
    )
    state.task_analysis_attempts = list(result.attempts)
    state.accepted_task_analysis = result.accepted
    latest = result.attempts[-1]
    if result.accepted is None:
        state.answer = "任务理解提案未通过确定性准入。"
        state.add_event("answer_completed", {
            "reason": "task_analysis_not_admitted",
            "business_result": False,
        })
        state.add_event("task_analysis_denied", {
            "attempts": [item.model_dump(mode="json") for item in result.attempts],
        })
        return {
            "task_analysis_attempts": state.task_analysis_attempts,
            "accepted_task_analysis": None,
            "answer": state.answer,
            "events": state.events,
        }
    decision = result.accepted.analysis
    if decision.outcome == "rejected":
        state.answer = decision.rejection_reason
        state.add_event("answer_completed", {"reason": "task_rejected"})
    state.invocation_batch.invocations = []

    event = state.add_event("task_analyzed", {
        "proposal": latest.proposal.model_dump(mode="json"),
        "admission": latest.admission.model_dump(mode="json"),
        "attempts": [item.model_dump(mode="json") for item in result.attempts],
        "accepted_analysis_ref": result.accepted.accepted_analysis_id,
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
        "task_analysis_attempts": state.task_analysis_attempts,
        "accepted_task_analysis": state.accepted_task_analysis,
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
    if decision is None:
        return "未提供任务理解结果。"
    if decision.error == "analyzer_unavailable" or decision.requires_clarification:
        return decision.clarification_prompt
    if decision.outcome == "rejected":
        return decision.rejection_reason
    return "已识别目标：" + "；".join(goal.description for goal in decision.goals)


def _node_finalize_entry_result(
    state: RunCheckpoint,
    *,
    deps: StepExecutionContext,
) -> dict:
    waiting_for_environment = bool(
        state.task_runtime is not None
        and state.task_runtime.lifecycle in {"awaiting_input", "paused"}
        and not state.errors
    )
    if (
        state.task_runtime is not None
        and state.task_runtime.lifecycle not in {
            "completed", "terminated", "awaiting_input", "paused",
        }
        and not state.answer_completed
    ):
        state.errors.append("completion_verifier_did_not_accept_task")
    if not state.errors and state.completion_report is not None and state.completion_report.status == "complete":
        proposal = _compose_final_answer(state, deps)
        if proposal is None:
            state.errors.append("final_answer_composition_unavailable")
            state.answer = ""
            state.add_event("final_answer_composition_unavailable", {
                "status": "failed_closed",
            })
        else:
            state.final_answer_proposal = proposal
            state.answer = proposal.answer
            state.add_event("final_answer_admitted", {
                "proposal": proposal.model_dump(mode="json"),
                "admission": (
                    state.final_answer_admission.model_dump(mode="json")
                    if state.final_answer_admission else None
                ),
            })
    if waiting_for_environment:
        state.add_event("agent_run_waiting", {
            "lifecycle": state.task_runtime.lifecycle if state.task_runtime else None,
            "reason": "awaiting_environment_change",
        })
    elif state.errors:
        state.add_event("run_failed", {"errors": state.errors})
    else:
        if not any(event.type == "answer_completed" for event in state.events):
            state.add_event("answer_completed", {"answer": state.answer})
        state.add_event("run_completed", {
            "answer": state.answer,
            "result_contracts": [
                goal.result_contract for goal in state.accepted_task_analysis.analysis.goals
            ] if state.accepted_task_analysis else [],
        })
        logger.info(
            "finalize_entry_result relies on checkpoint messages run_id=%s intent=%s answer_len=%d",
            state.run_id,
            _primary_result_contract(
                state.accepted_task_analysis.analysis if state.accepted_task_analysis else None
            ),
            len(state.answer or ""),
        )
    logger.info(
        "finalize_entry_result run_id=%s intent=%s errors=%d",
        state.run_id,
        _primary_result_contract(
            state.accepted_task_analysis.analysis if state.accepted_task_analysis else None
        ),
        len(state.errors),
    )
    result = {
        "events": state.events,
        "updated_at": state.updated_at,
        "context_projections": state.context_projections,
        "final_answer_proposal": state.final_answer_proposal,
        "final_answer_admission": state.final_answer_admission,
        "answer": state.answer,
        "errors": state.errors,
    }
    if not state.errors and state.answer:
        result["messages"] = [
            AIMessage(content=state.answer, id=f"{state.run_id}:assistant")
        ]
    return result


def _compose_final_answer(
    state: RunCheckpoint,
    deps: StepExecutionContext,
) -> FinalAnswerProposal | None:
    if state.task_contract is None or deps.model_client is None:
        return None
    from personal_agent.capabilities.contracts.model import StructuredModelRequest

    if state.completion_report is None:
        return None
    materialized = _materialize_final_answer_context(state, deps)
    verified_goal_refs = state.completion_report.verified_goal_ids
    report_refs = tuple(
        report.report_id for report in state.verification_reports.values()
    )
    allowed_citations = tuple(
        str(getattr(item, "id", None) or getattr(item, "url", None) or index)
        for index, item in enumerate(state.citations)
    )
    feedback: dict[str, object] | None = None
    prior_proposal: FinalAnswerProposal | None = None
    output_type = _FinalAnswerBody if allowed_citations else _FinalAnswerWithoutCitations
    for attempt in range(2):
        try:
            response = deps.model_client.generate(StructuredModelRequest(
                operation="final_answer_composition",
                version="v1",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Compose the final business answer using only verified goals, admitted evidence, "
                            "execution facts, and receipts in the supplied context. Do not claim an unverified "
                            "outcome, invent citations, or copy a tool title as the answer. Return only the "
                            "structured object. When allowed_citation_refs is empty, the output schema deliberately "
                            "has no citation field: do not mention or invent citations. If output feedback is supplied, "
                            "revise only the rejected output."
                        ),
                    },
                    {"role": "user", "content": json.dumps({
                        "context": materialized.model_payload(),
                        "allowed_citation_refs": allowed_citations,
                        "output_feedback": feedback,
                    }, ensure_ascii=False, default=str)},
                ],
                output_type=output_type,
                context_projection_ref=materialized.projection_id,
                temperature=0,
                max_tokens=1200,
                kind="structured",
                metadata={"task_id": state.task_contract.task_id, "attempt": attempt},
            ))
        except Exception:
            logger.exception("Final answer composition failed")
            return None
        body = response.value
        proposal = FinalAnswerProposal(
            task_ref=state.task_contract.task_id,
            task_revision=state.task_contract.revision,
            verified_goal_refs=verified_goal_refs,
            verification_report_refs=report_refs,
            answer=body.answer,
            citation_refs=(
                body.citation_refs
                if isinstance(body, _FinalAnswerBody) else ()
            ),
            supersedes_proposal_ref=(prior_proposal.proposal_id if prior_proposal else None),
            revision_feedback_ref=(
                state.decision_feedback[-1].feedback_id
                if prior_proposal is not None and state.decision_feedback else None
            ),
            revision_attempt=attempt,
        )
        admission = FinalAnswerAdmission().admit(
            state.task_contract,
            state.task_runtime.revision if state.task_runtime is not None else 0,
            state.completion_report,
            proposal,
            required_report_refs=report_refs,
            allowed_citation_refs=allowed_citations,
        )
        state.final_answer_admission = admission
        if admission.verdict == "accepted":
            return proposal
        if admission.feedback is None:
            return None
        state.decision_feedback.append(admission.feedback)
        feedback = admission.feedback.model_dump(mode="json")
        prior_proposal = proposal
        state.add_event("final_answer_feedback_created", feedback)
    return None


def _materialize_final_answer_context(
    state: RunCheckpoint,
    deps: StepExecutionContext,
):
    """Create the only input surface for final answer composition.

    Decision ownership: this is a closed-world context derivation.  Its only
    inputs are the completed contract, admitted verification facts and the
    already-produced draft.  It never selects a new goal, evidence item, or
    business result.
    """
    if state.task_contract is None or state.task_runtime is None or state.completion_report is None:
        raise ValueError("final composition requires completed task state")
    item = ContextItem(
        item_id=(
            f"final-composition:{state.task_contract.task_id}:"
            f"{state.task_contract.revision}:{state.task_runtime.revision}"
        ),
        category="run",
        kind="final_composition_contract",
        provenance="runtime",
        trust="runtime",
        admission="admitted",
        summary=state.task_contract.user_goal,
        payload={
            "authority_tier": "system_policy",
            "task": state.task_contract.model_dump(mode="json"),
            "completion_report": state.completion_report.model_dump(mode="json"),
            "goal_verification_reports": {
                key: value.model_dump(mode="json")
                for key, value in state.verification_reports.items()
            },
            "execution_fact_reports": {
                key: value.model_dump(mode="json")
                for key, value in state.execution_fact_reports.items()
            },
            "tool_results": state.tool_results[-12:],
            "invocation_results": state.invocation_batch.results,
            "draft_answer": state.answer,
        },
    )
    budget = ContextBudget(
        model_profile="runtime-default",
        tokenizer_profile="runtime-default",
        max_context_tokens=16_384,
        safety_margin=512,
        reserved_output_tokens=2_048,
    )
    projection = deps.context_manager.project_contract(
        (item,),
        purpose="final_composition",
        budget=budget,
        source_snapshot=RuntimeSnapshotRef(
            run_id=state.run_id,
            task_id=state.task_contract.task_id,
            task_revision=state.task_contract.revision,
            runtime_revision=state.task_runtime.revision,
            event_sequence=state.task_runtime.last_event_sequence,
        ),
    )
    materialized = deps.context_gateway.open(
        projection,
        (item,),
        purpose="final_composition",
    )
    state.context_projections.append(projection)
    state.add_event("context_projected", projection.model_dump(mode="json"))
    state.add_event("context_materialized", {
        "projection_id": projection.projection_id,
        "purpose": "final_composition",
        "materialized_refs": materialized.materialized_refs,
    })
    return materialized
