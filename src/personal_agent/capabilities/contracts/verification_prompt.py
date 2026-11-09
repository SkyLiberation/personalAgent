"""Render each verifier's own task and history for invocation and budgeting."""
import json
from difflib import unified_diff
from typing import Literal
from pydantic import Field, create_model
from personal_agent.kernel.llm_schemas import native_output_parameters
from .model import StructuredModelRequest, sealed_context_projection_ref

from personal_agent.kernel.prompt_registry import PromptCatalog
from .verification import (
    AnswerGoalAssessment, GoalComplianceAnswerContext, VerificationContext, VerificationCriterion, VerificationCriterionResult,
    SemanticVerificationReceipt, SemanticVerificationReport, UserRequirementAssessment, VerificationKind,
)

GOAL_COMPLIANCE_OPERATION = "interaction_goal_compliance_verification"


def goal_compliance_messages(stage: str, rounds: tuple[str, ...], *, prompts: PromptCatalog) -> list[dict[str, str]]:
    system = prompts.render("interaction_verification.compliance", stage=stage)
    return [{"role": "system", "content": system},
            *({"role": "user", "content": content} for content in rounds)]


def goal_compliance_answer_request(context: GoalComplianceAnswerContext, draft: str,
                                   *, prompts: PromptCatalog) -> StructuredModelRequest[AnswerGoalAssessment]:
    prompt = prompts.get("interaction_verification.answer")
    criteria = task_verification_criteria("answer", prompts=prompts)
    system = prompts.render(prompt.name, criteria_json=json.dumps([item.criterion for item in criteria], ensure_ascii=False))
    pending = prompts.render("interaction_verification.compliance.pending_answer",
        submission_id=context.submission_id, disposition=context.disposition, draft=draft)
    rounds = (*context.rounds[:-1], context.rounds[-1] + "\n\n" + pending)
    messages = goal_compliance_messages(system, rounds, prompts=prompts)
    projection = sealed_context_projection_ref(purpose=GOAL_COMPLIANCE_OPERATION, messages=messages)
    return StructuredModelRequest(operation=GOAL_COMPLIANCE_OPERATION, version=prompt.version,
        messages=messages, output_type=AnswerGoalAssessment, output_transport="native_tool",
        max_tokens=32_768, temperature=0, context_projection_ref=projection,
        consumer_key=f"answer:{prompt.version}:{projection}", metadata={"component": "interaction_verifier"})


def task_verification_output(kind: VerificationKind) -> type[UserRequirementAssessment]:
    return AnswerGoalAssessment if kind == "answer" else UserRequirementAssessment


def task_verification_criteria(
    kind: VerificationKind, *, prompts: PromptCatalog,
) -> tuple[VerificationCriterion, ...]:
    """Bind only the current responsibility's runtime-owned contract."""
    return (VerificationCriterion(
        criterion_id="r1", criterion=prompts.get(f"interaction_verification.{kind}.criteria").template,
    ),)


def verification_messages(
    context: VerificationContext, criteria: tuple[VerificationCriterion, ...], *, prompts: PromptCatalog,
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": prompts.render(f"interaction_verification.{context.kind}",
        criteria_json=json.dumps([item.criterion for item in criteria], ensure_ascii=False))}]
    for turn in context.turns:
        if context.kind == "goal":
            messages.append({"role": "user", "content": prompts.render("interaction_verification.history.user_turn",
                number=turn.user_turn, question=turn.question)})
        else:
            messages.append({"role": "system", "content": prompts.render(
                "interaction_verification.answer.history_turn", number=turn.user_turn)})
        if context.kind == "goal" and turn is context.turns[-1]:
            messages.append({"role": "system", "content": prompts.render("interaction_verification.history.request",
                active_goal=context.active_goal or prompts.get("interaction_verification.history.no_goal").template)})
        if turn.summary is not None:
            messages.append({"role": "system", "content": prompts.render(
                "interaction_verification.history.compacted", summary=turn.summary)})
        shown_goal = None
        for number, item in enumerate(turn.events, 1):
            values = {"number": number, "draft": item.content, "submission_id": item.submission_id}
            if (context.kind == "goal" and turn is context.turns[-1] and item is turn.events[-1]
                    and item.verdict is None and context.active_goal is not None):
                delta = "\n".join(unified_diff(context.active_goal.splitlines(), item.content.splitlines(),
                                               fromfile="active", tofile="candidate", n=0, lineterm=""))
                if delta:
                    messages.append({"role": "system", "content": prompts.render(
                        "interaction_verification.history.goal_delta", delta=delta)})
            if context.kind == "answer":
                values["disposition"] = item.disposition
                goal = item.verified_goal
                values["goal_receipt_id"] = (goal.receipt_id if goal is not None else
                    prompts.get("interaction_verification.answer.goal_unavailable").template)
                if goal is not None and goal.receipt_id != shown_goal:
                    messages.append({"role": "system", "content": prompts.render(
                        "interaction_verification.answer.verified_goal", draft=goal.verified_draft,
                        judgment=verification_judgment_text(goal, prompts=prompts))})
                    shown_goal = goal.receipt_id
                unverified = item.unverified_goal
                if unverified is not None:
                    values["goal_receipt_id"] = prompts.render(
                        "interaction_verification.answer.unverified_goal_reference", submission_id=unverified.submission_id)
                    if unverified.submission_id != shown_goal:
                        messages.append({"role": "system", "content": prompts.render(
                            "interaction_verification.answer.unverified_goal",
                            draft=unverified.content, submission_id=unverified.submission_id)})
                        shown_goal = unverified.submission_id
            messages.append({"role": "user", "content": prompts.render(
                f"interaction_verification.{context.kind}.history_item", **values)})
            if item.verdict is not None:
                messages.append({"role": "system", "content": prompts.render(
                    "interaction_verification.history.judgment", submission_id=item.submission_id,
                    judgment=verification_judgment_text(item.verdict, prompts=prompts))})
    return messages


def verification_judgment_text(receipt: SemanticVerificationReceipt, *, prompts: PromptCatalog) -> str:
    """Project a bound verdict without changing its canonical report or acceptance."""
    if receipt.verdict == "passed":
        return prompts.render(f"interaction_verification.{receipt.checked_kind}.passed",
            receipt_id=receipt.receipt_id, draft_digest=receipt.draft_digest)
    return receipt.model_dump_json(include={"verdict", "criterion_results", "revision_feedback"})


def bound_verification_report(
    report_type: type[SemanticVerificationReport],
    criteria: tuple[VerificationCriterion, ...],
) -> type[SemanticVerificationReport]:
    """Expose only the current request's references, including system criteria."""
    allowed_ids = tuple(item.criterion_id for item in criteria)
    result_type = create_model(
        "CurrentVerificationCriterionResult",
        __base__=VerificationCriterionResult,
        criterion_id=(
            Literal[allowed_ids],
            Field(description="只引用当前 success_criteria 的 criterion_id。"),
        ),
    )
    return create_model(
        f"Current{report_type.__name__}",
        __base__=report_type,
        criterion_results=(
            tuple[result_type, ...],
            Field(min_length=len(criteria), max_length=len(criteria)),
        ),
    )


def verification_input_size(context: VerificationContext, criteria: tuple[VerificationCriterion, ...],
                            *, prompts: PromptCatalog) -> int:
    """ASCII wire estimate with the actual bound native-output schema and wrapper."""
    output = task_verification_output(context.kind)
    body = {"messages": verification_messages(context, criteria, prompts=prompts),
        "tools": [{"type": "function", "function": {"name": "structured_output",
            "description": prompts.get("structured.native_output.description").template,
            "parameters": prompts.localize_schema(native_output_parameters(output)), "strict": False}}],
        "tool_choice": "required", "max_tokens": 32768, "temperature": 0,
        "stream": True, "stream_options": {"include_usage": True}}
    return len(json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii"))
