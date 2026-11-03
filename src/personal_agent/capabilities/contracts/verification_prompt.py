"""Render each verifier's own task and history for invocation and budgeting."""
import json
from typing import Literal
from pydantic import Field, create_model
from personal_agent.kernel.llm_schemas import native_output_parameters

from personal_agent.kernel.prompt_registry import PromptCatalog
from .verification import (
    VerificationContext, VerificationCriterion, VerificationCriterionResult,
    SemanticVerificationReport, UserRequirementAssessment, VerificationKind,
)


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
        records = []
        for number, item in enumerate(turn.events, 1):
            values = {"number": number, "draft": item.content,
                "judgment_json": (item.verdict.model_dump_json(include={"verdict", "criterion_results", "revision_feedback"})
                    if item.verdict is not None else prompts.get("interaction_verification.history.pending").template)}
            if context.kind == "answer":
                values["disposition"] = item.disposition
            records.append(prompts.render(f"interaction_verification.{context.kind}.history_item", **values))
        records = "\n\n".join(records)
        if turn.summary is not None:
            records = prompts.render("interaction_verification.history.compacted", summary=turn.summary) + "\n\n" + records
        content = prompts.render("interaction_verification.history.user_turn", number=turn.user_turn,
            question=turn.question, rounds=records)
        if turn is context.turns[-1]:
            content = prompts.render("interaction_verification.history.request",
                active_goal=context.active_goal or prompts.get("interaction_verification.history.no_goal").template) + "\n\n" + content
        messages.append({"role": "user", "content": content})
    return messages


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
    output = UserRequirementAssessment
    body = {"messages": verification_messages(context, criteria, prompts=prompts),
        "tools": [{"type": "function", "function": {"name": "structured_output",
            "description": prompts.get("structured.native_output.description").template,
            "parameters": prompts.localize_schema(native_output_parameters(output)), "strict": False}}],
        "tool_choice": "required", "max_tokens": 32768, "temperature": 0,
        "stream": True, "stream_options": {"include_usage": True}}
    return len(json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii"))
