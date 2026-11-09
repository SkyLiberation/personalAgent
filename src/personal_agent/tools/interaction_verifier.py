from __future__ import annotations

import json
from collections.abc import Callable
from hashlib import sha256

from langchain_core.tools import BaseTool, tool
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.model import (
    StructuredModelRequest,
    StructuredModelResponse,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.verification import (
    BoundVerificationCriterionResult,
    CitedDraftUnit,
    CitedSupportRejection,
    GoalComplianceAnswerContext,
    OverreachReport,
    SemanticVerificationReceipt,
    SemanticVerificationReport,
    SourceReadingState,
    UserRequirementAssessment,
    VerificationCriterion,
    VerificationCriterionResult,
    VerificationContext,
    VerificationKind,
)
from personal_agent.capabilities.contracts.verification_prompt import (
    goal_compliance_answer_request, verification_messages, bound_verification_report,
    task_verification_criteria, task_verification_output,
)
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS
from personal_agent.kernel.contracts.scope import ExecutionScope
from personal_agent.tools.base import (
    ToolArtifact,
    governance_extras,
    tool_failure,
    tool_response,
    tool_success,
    require_gateway_context,
)


class VerifyInteractionDraftArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    draft: str = Field(min_length=1)
    success_criteria: tuple[str, ...] = Field(min_length=1)
    cited_units: tuple[CitedDraftUnit, ...] = ()
    source_reading_state: tuple[SourceReadingState, ...] = ()
    task_context: GoalComplianceAnswerContext | VerificationContext | None = None

    @model_validator(mode="after")
    def check_draft_coverage(self):
        if (
            self.cited_units
            and "".join(unit.draft for unit in self.cited_units) != self.draft
        ):
            raise ValueError(
                "cited units must preserve the entire exact draft in order"
            )
        if isinstance(self.task_context, VerificationContext):
            if self.task_context.kind != "goal" or self.task_context.turns[-1].events[-1].content != self.draft:
                raise ValueError("goal verification history must end with the exact goal submission")
        for unit in self.cited_units:
            ids = [evidence.id for evidence in unit.execution_evidence]
            if len(ids) != len(set(ids)):
                raise ValueError("cited evidence ids must be unique within their unit")
        return self


def _user_requirement_report(
    assessment: UserRequirementAssessment, criterion: VerificationCriterion, *,
    kind: VerificationKind, prompts: PromptCatalog,
) -> SemanticVerificationReport:
    """Project actual requirement judgments into the existing receipt contract."""
    statuses = tuple(check.status for check in assessment.checks)
    status = ("not_satisfied" if "not_satisfied" in statuses else
              "insufficient_evidence" if "insufficient_evidence" in statuses else "satisfied")
    feedback_prompt = ("interaction_verification.answer.requirement_feedback" if kind == "answer"
                       else "interaction_verification.requirement_feedback")
    feedback = tuple(prompts.render(
        feedback_prompt,
        requirement=check.requirement, status=check.status, feedback=check.feedback,
    ) for check in assessment.checks)
    return SemanticVerificationReport(
        criterion_results=(VerificationCriterionResult(
            criterion_id=criterion.criterion_id, status=status, feedback="\n\n".join(feedback),
        ),),
        revision_feedback="\n\n".join(
            text for check, text in zip(assessment.checks, feedback, strict=True)
            if check.status != "satisfied"
        ),
    )


def build_verify_interaction_draft_tool(
    generate: Callable[[ExecutionScope, StructuredModelRequest], StructuredModelResponse],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> BaseTool:
    @tool(
        "verify_interaction_draft",
        description=(
            "Runtime-invoked semantic verification of an interaction draft against runtime-derived "
            "success criteria using visible evidence; task_context selects its goal-definition or answer-delivery check. "
            "Returns a typed SemanticVerificationReceipt; it cannot execute effects or mark completion. "
            "Not exposed to the semantic decision maker: the interaction runtime decides when a draft is "
            "verified, so the model can neither skip verification nor author the criteria it is judged by."
        ),
        args_schema=VerifyInteractionDraftArgs,
        response_format="content_and_artifact",
        extras=governance_extras(
            exposure="workflow_activity",
            risk_level="low",
            side_effects=("none",),
            permission_scope="interaction:verify",
            timeout_seconds=None,
            max_retries=0,
            rate_limit_per_minute=20,
            emits_verified_artifact=True,
        ),
    )
    def verify_interaction_draft(
        draft: str,
        success_criteria: tuple[str, ...],
        config: RunnableConfig,
        cited_units: tuple[CitedDraftUnit, ...] = (),
        source_reading_state: tuple[SourceReadingState, ...] = (),
        task_context: GoalComplianceAnswerContext | VerificationContext | None = None,
    ):
        scope = require_gateway_context(config, prompts=prompts).execution_scope
        prompt = prompts.get(f"interaction_verification.{task_context.kind}" if task_context is not None
            else "interaction_verification.system")
        support_prompt = prompts.get("interaction_verification.source_support")
        if task_context is not None:
            criteria = task_verification_criteria(task_context.kind, prompts=prompts)
            verification_criteria = tuple(item.criterion for item in criteria)
            if success_criteria != verification_criteria:
                raise ValueError("task verification requires its responsibility's runtime-owned criteria")
        else:
            verification_criteria = tuple(dict.fromkeys((*success_criteria, support_prompt.template)))
            criteria = tuple(
                VerificationCriterion(criterion_id=f"r{index}", criterion=text)
                for index, text in enumerate(verification_criteria, start=1)
            )
        criteria_context = [item.model_dump(mode="json") for item in criteria]
        verification_input = VerifyInteractionDraftArgs(
            draft=draft,
            success_criteria=success_criteria,
            cited_units=cited_units,
            source_reading_state=source_reading_state, task_context=task_context,
        )
        units = verification_input.cited_units or (CitedDraftUnit(draft=draft),)
        if task_context is not None:
            verification_payload = {"draft": draft, "task_context": task_context.model_dump(mode="json")}
        else:
            verification_payload = {
                "draft": draft,
                "success_criteria": criteria_context,
                "execution_evidence": [
                    evidence.model_dump(mode="json", exclude={"id"})
                    for unit in units for evidence in unit.execution_evidence
                ],
                "source_reading_state": [state.model_dump(mode="json")
                    for state in verification_input.source_reading_state],
            }
        cited_prompt = prompts.get("interaction_verification.cited_support")
        verification_key = sha256(verification_input.model_dump_json().encode("utf-8")).hexdigest()
        for unit_index, unit in enumerate(units if task_context is None else ()):
            if not unit.draft.strip():
                continue
            cited_messages = [
                {"role": "system", "content": cited_prompt.template},
                {"role": "user", "content": unit.model_dump_json()},
            ]
            support = generate(
                scope,
                StructuredModelRequest(
                    operation="interaction_cited_support",
                    consumer_key=f"cited:{verification_key}:{unit_index}",
                    version=cited_prompt.version,
                    messages=cited_messages,
                    output_type=OverreachReport,
                    output_transport="native_tool",
                    context_projection_ref=sealed_context_projection_ref(
                        purpose="interaction_cited_support",
                        messages=cited_messages,
                    ),
                    max_tokens=32_768,
                    temperature=0,
                    metadata={"component": "interaction_verifier"},
                )
            ).value
            valid_ids = {evidence.id for evidence in unit.execution_evidence}
            for finding in support.findings:
                if len(set(finding.evidence_ids)) != len(
                    finding.evidence_ids
                ) or not set(finding.evidence_ids).issubset(valid_ids):
                    raise ValueError(
                        "support finding must reference only submitted evidence"
                    )
            if support.findings:
                rejection = CitedSupportRejection(
                    rejected_draft=draft,
                    checked_draft=unit.draft,
                    findings=support.findings,
                    explanation=prompts.render("verification.cited_support_rejection.explanation"),
                )
                return tool_response(
                    ToolArtifact(
                        ok=False,
                        data=rejection.model_dump(mode="json"),
                        error=rejection.explanation,
                        error_kind="unrecoverable",
                    )
                )
        if isinstance(task_context, GoalComplianceAnswerContext):
            request = goal_compliance_answer_request(task_context, draft, prompts=prompts)
        else:
            messages = (verification_messages(task_context, criteria, prompts=prompts)
                        if task_context is not None else [
                {"role": "system", "content": prompt.template},
                {"role": "user", "content": json.dumps(verification_payload, ensure_ascii=False)},
            ])
            operation = "interaction_goal_verification" if task_context is not None else "interaction_semantic_verification"
            request = StructuredModelRequest(
                operation=operation,
                consumer_key="semantic:" + sha256(json.dumps(verification_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest(),
                version=prompt.version,
                messages=messages,
                output_type=(task_verification_output(task_context.kind) if task_context is not None else
                             bound_verification_report(SemanticVerificationReport, criteria)),
                output_transport="native_tool",
                context_projection_ref=sealed_context_projection_ref(
                    purpose=operation,
                    messages=messages,
                ),
                max_tokens=32_768,
                temperature=0,
                metadata={
                    "component": "interaction_verifier",
                    **({"source_support_prompt_version": support_prompt.version} if task_context is None else {}),
                },
            )
        response = generate(scope, request)
        report = (_user_requirement_report(response.value, criteria[0], kind=task_context.kind, prompts=prompts)
                  if task_context is not None else response.value)
        reported_ids = tuple(result.criterion_id for result in report.criterion_results)
        criteria_by_id = {item.criterion_id: item.criterion for item in criteria}
        if len(reported_ids) != len(criteria) or set(reported_ids) != set(
            criteria_by_id
        ):
            return tool_response(
                tool_failure(
                    prompts.render('tools.verification.criteria_coverage'),
                )
            )
        statuses = tuple(result.status for result in report.criterion_results)
        verdict = (
            "passed" if all(status == "satisfied" for status in statuses) else "failed"
        )
        if verdict == "failed" and not report.revision_feedback.strip():
            derived_feedback = "\n".join(
                f"{criteria_by_id[result.criterion_id]}: {result.feedback.strip()}"
                for result in report.criterion_results
                if result.status != "satisfied" and result.feedback.strip()
            )
            if not derived_feedback:
                raise ValueError(
                    "semantic verifier must provide feedback for failed criteria"
                )
            report = report.model_copy(
                update={
                    "revision_feedback": derived_feedback,
                }
            )
        criteria_payload = json.dumps(
            success_criteria,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        draft_digest = sha256(draft.encode("utf-8")).hexdigest()
        receipt = SemanticVerificationReceipt(
            **report.model_dump(mode="python", exclude={"criterion_results"}),
            criterion_results=tuple(
                BoundVerificationCriterionResult(
                    **result.model_dump(mode="python"),
                    criterion=criteria_by_id[result.criterion_id],
                )
                for result in report.criterion_results
            ),
            checked_kind=task_context.kind if task_context is not None else "answer",
            verdict=verdict,
            receipt_id=f"svr_{verification_key[:20]}",
            verified_draft=draft,
            draft_digest=draft_digest,
            success_criteria=tuple(success_criteria),
            criteria_digest=sha256(criteria_payload.encode("utf-8")).hexdigest(),

        )
        return tool_response(tool_success(receipt.model_dump(mode="json")))

    return verify_interaction_draft


__all__ = [
    "SemanticVerificationReceipt",
    "SemanticVerificationReport",
    "VerifyInteractionDraftArgs",
    "build_verify_interaction_draft_tool",
]
