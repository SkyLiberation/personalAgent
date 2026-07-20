"""Semantic task understanding without execution routing or capability selection."""

from __future__ import annotations

import logging
import json
from typing import Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.model import StructuredModelClient, StructuredModelRequest
from personal_agent.kernel.contracts.capability_values import CapabilityOperation
from personal_agent.kernel.logging_utils import log_event
from personal_agent.kernel.models import EntryInput
from personal_agent.governance.contracts.admission import StageAdmissionDecision
from personal_agent.kernel.prompts import get_prompt, render_prompt

logger = logging.getLogger(__name__)

ConversationMessage = dict[str, str]
AnalysisOutcome = Literal["ready", "clarify", "rejected"]
ResultContract = Literal["response", "artifact", "external_state"]
SideEffectIntent = Literal["none", "mutation"]
ResourceHintOrigin = Literal["user_explicit", "model_inferred"]
RelationKind = Literal["consumes_output", "requires_completion", "ordering_preference"]
RelationOrigin = Literal["user_explicit", "model_inferred", "runtime_derived"]


class EvidenceRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    citation_required: bool = False
    minimum_source_count: int | None = Field(default=None, ge=1)
    contradiction_check: bool = False


class SuccessCriterionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1)
    origin: ResourceHintOrigin


class GoalConstraintDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    description: str = Field(min_length=1)
    origin: ResourceHintOrigin


class TaskAnalysisGroundingClaim(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_text: str = Field(min_length=1)
    output_field_ref: str = Field(min_length=1)
    transform: Literal["identity"] = "identity"


class ResourceHint(BaseModel):
    """Provider-neutral resource need, optionally constrained by the user."""

    model_config = ConfigDict(extra="forbid")

    semantic_domain: str = Field(min_length=1)
    resource_types: list[str] = Field(default_factory=list)
    operations: list[CapabilityOperation] = Field(min_length=1)
    locator: str | None = None
    user_required_provider: str | None = None
    origin: ResourceHintOrigin = "model_inferred"
    freshness_required: bool = False

    @model_validator(mode="after")
    def _validate_user_binding(self) -> "ResourceHint":
        if self.user_required_provider and self.origin != "user_explicit":
            raise ValueError("only a user-explicit resource hint may bind a provider")
        return self


class GoalDraft(BaseModel):
    """One verifiable result without an execution method or topology."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    result_contract: ResultContract = "response"
    success_criteria: list[SuccessCriterionDraft] = Field(min_length=1)
    constraints: list[GoalConstraintDraft] = Field(default_factory=list)
    side_effect_intent: SideEffectIntent = "none"
    evidence_requirement: EvidenceRequirement | None = None
    resource_hints: list[ResourceHint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_result_contract(self) -> "GoalDraft":
        if self.result_contract == "external_state" and self.side_effect_intent != "mutation":
            raise ValueError("external_state result requires mutation side_effect_intent")
        if self.side_effect_intent == "mutation" and not self.resource_hints:
            raise ValueError("mutation result requires resource_hints")
        return self


class GoalRelationDraft(BaseModel):
    """Initial relation hypothesis using 1-based goal indexes."""

    predecessor: int = Field(ge=1)
    successor: int = Field(ge=1)
    kind: RelationKind
    origin: Literal["user_explicit", "model_inferred"] = "model_inferred"
    rationale: str = Field(min_length=1)


class ClarificationDraft(BaseModel):
    missing_information: list[str] = Field(min_length=1)
    prompt: str = Field(min_length=1)


class TaskAnalysisProposalBody(BaseModel):
    """Model-owned semantic proposal body for task understanding."""

    user_goal: str = Field(min_length=1)
    outcome: AnalysisOutcome
    goals: list[GoalDraft] = Field(default_factory=list)
    relations: list[GoalRelationDraft] = Field(default_factory=list)
    clarification: ClarificationDraft | None = None
    rejection_reason: str | None = None
    grounding_claims: tuple[TaskAnalysisGroundingClaim, ...] = ()

    @model_validator(mode="after")
    def _validate_contract(self) -> "TaskAnalysisProposalBody":
        if self.outcome == "ready":
            if not self.goals:
                raise ValueError("ready output requires at least one goal")
            if self.clarification is not None or self.rejection_reason:
                raise ValueError("ready output cannot clarify or reject")
            size = len(self.goals)
            for relation in self.relations:
                if relation.predecessor > size or relation.successor > size:
                    raise ValueError("goal relation references an unknown 1-based goal index")
                if relation.predecessor == relation.successor:
                    raise ValueError("goal relation cannot reference the same goal")
            return self
        if self.goals or self.relations:
            raise ValueError(f"{self.outcome} output cannot contain goals or relations")
        if self.outcome == "clarify":
            if self.clarification is None:
                raise ValueError("clarify output requires clarification")
            if self.rejection_reason:
                raise ValueError("clarify output cannot contain rejection_reason")
            return self
        if not self.rejection_reason:
            raise ValueError("rejected output requires rejection_reason")
        if self.clarification is not None:
            raise ValueError("rejected output cannot contain clarification")
        return self


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_id: str
    description: str
    result_contract: ResultContract = "response"
    success_criteria: list[SuccessCriterionDraft] = Field(min_length=1)
    constraints: list[GoalConstraintDraft] = Field(default_factory=list)
    side_effect_intent: SideEffectIntent = "none"
    evidence_requirement: EvidenceRequirement | None = None
    resource_hints: list[ResourceHint] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_result_contract(self) -> "Goal":
        if self.result_contract == "external_state" and self.side_effect_intent != "mutation":
            raise ValueError("external_state result requires mutation side_effect_intent")
        if self.side_effect_intent == "mutation" and not self.resource_hints:
            raise ValueError("mutation result requires resource_hints")
        return self


class GoalRelation(BaseModel):
    predecessor_goal_id: str
    successor_goal_id: str
    kind: RelationKind
    origin: RelationOrigin
    rationale: str


class TaskAnalysis(BaseModel):
    """Provider-neutral task understanding. It contains no execution policy."""

    model_config = ConfigDict(extra="forbid")

    user_goal: str = Field(min_length=1)
    outcome: AnalysisOutcome = "ready"
    goals: list[Goal] = Field(default_factory=list)
    relations: list[GoalRelation] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    rejection_reason: str = ""
    error: Literal["analyzer_unavailable"] | None = None

    @property
    def requires_clarification(self) -> bool:
        return self.outcome == "clarify"

    @model_validator(mode="after")
    def _validate_domain_contract(self) -> "TaskAnalysis":
        if self.outcome == "ready" and not self.goals:
            raise ValueError("ready analysis requires at least one goal")
        if self.outcome != "ready" and (self.goals or self.relations):
            raise ValueError(f"{self.outcome} analysis cannot contain goals or relations")
        if self.outcome == "clarify" and not self.clarification_prompt:
            raise ValueError("clarify analysis requires clarification_prompt")
        if self.outcome == "rejected" and not self.rejection_reason:
            raise ValueError("rejected analysis requires rejection_reason")
        return self


class TaskAnalysisProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(default_factory=lambda: uuid4().hex)
    input_ref: str = Field(min_length=1)
    input_digest: str = Field(min_length=1)
    source: Literal["model", "contract_derivation"] = "model"
    control_error: Literal["analyzer_unavailable"] | None = None
    body: TaskAnalysisProposalBody
    supersedes_proposal_ref: str | None = None
    revision_feedback_ref: str | None = None
    revision_attempt: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_control_error_owner(self) -> "TaskAnalysisProposal":
        if self.control_error is not None and self.source != "contract_derivation":
            raise ValueError("only control derivation may report analyzer availability")
        return self


class AcceptedTaskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted_analysis_id: str = Field(default_factory=lambda: uuid4().hex)
    proposal_ref: str
    admission_ref: str
    input_ref: str
    input_digest: str
    analysis: TaskAnalysis
    grounding_records: tuple["TaskAnalysisProvenanceRecord", ...] = ()


class TaskAnalysisProvenanceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_ref: str
    source_digest: str
    output_field_ref: str
    output_digest: str
    transform: Literal["identity"] = "identity"


class TaskAnalysisAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal: TaskAnalysisProposal
    admission: StageAdmissionDecision


class TaskAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempts: tuple[TaskAnalysisAttempt, ...] = Field(min_length=1)
    accepted: AcceptedTaskAnalysis | None = None


class TaskAnalyzer(Protocol):
    def analyze(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> TaskAnalysisResult: ...


class DefaultTaskAnalyzer:
    """Use semantic model understanding; deterministic code handles structure only."""

    def __init__(self, model_client: StructuredModelClient | None) -> None:
        self._model_client = model_client

    def analyze(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> TaskAnalysisResult:
        from personal_agent.planning.task_analysis_admission import (
            AcceptedTaskAnalysisCompiler,
            TaskAnalysisAdmission,
            task_analysis_input_digest,
        )

        input_ref = f"entry:{entry_input.user_id}:{entry_input.session_id}"
        input_digest = task_analysis_input_digest(entry_input)
        if not entry_input.text.strip() and not entry_input.artifacts:
            body = _clarification_body(
                "请补充你想完成的具体目标。",
                ["明确的目标、问题或操作对象"],
            )
            proposal = TaskAnalysisProposal(
                input_ref=input_ref,
                input_digest=input_digest,
                source="contract_derivation",
                body=body,
            )
            admission = TaskAnalysisAdmission().admit(entry_input, proposal)
            accepted = AcceptedTaskAnalysisCompiler().compile(proposal, admission)
            self._log(entry_input, accepted.analysis, "structural_empty")
            return TaskAnalysisResult(
                attempts=(TaskAnalysisAttempt(proposal=proposal, admission=admission),),
                accepted=accepted,
            )

        feedback = None
        prior: TaskAnalysisProposal | None = None
        last_admission: StageAdmissionDecision | None = None
        attempts: list[TaskAnalysisAttempt] = []
        for attempt in range(3):
            body = self._analyze_with_model(
                _analysis_text(entry_input),
                conversation_messages or [],
                feedback=feedback,
            )
            if body is None:
                break
            proposal = TaskAnalysisProposal(
                input_ref=input_ref,
                input_digest=input_digest,
                body=body,
                supersedes_proposal_ref=prior.proposal_id if prior else None,
                revision_feedback_ref=(feedback.feedback_id if feedback else None),
                revision_attempt=attempt,
            )
            admission = TaskAnalysisAdmission().admit(
                entry_input,
                proposal,
                prior_proposal=prior,
                revision_feedback=feedback,
            )
            last_admission = admission
            attempts.append(TaskAnalysisAttempt(proposal=proposal, admission=admission))
            if admission.verdict == "accepted":
                accepted = AcceptedTaskAnalysisCompiler().compile(proposal, admission)
                self._log(entry_input, accepted.analysis, "semantic_model")
                return TaskAnalysisResult(attempts=tuple(attempts), accepted=accepted)
            feedback = admission.feedback
            prior = proposal
            if feedback is None or feedback.disposition != "revise_model":
                self._log_denial(entry_input, proposal, admission)
                return TaskAnalysisResult(attempts=tuple(attempts))

        if prior is not None and last_admission is not None:
            self._log_denial(entry_input, prior, last_admission)
            return TaskAnalysisResult(attempts=tuple(attempts))
        body = _clarification_body(
                "任务理解模型当前不可用，无法可靠推断目标和操作边界。请稍后重试。",
                ["可用的任务理解模型"],
            )
        proposal = TaskAnalysisProposal(
            input_ref=input_ref,
            input_digest=input_digest,
            source="contract_derivation",
            control_error="analyzer_unavailable",
            body=body,
        )
        admission = TaskAnalysisAdmission().admit(entry_input, proposal)
        accepted = AcceptedTaskAnalysisCompiler().compile(proposal, admission)
        self._log(entry_input, accepted.analysis, "analyzer_unavailable")
        return TaskAnalysisResult(
            attempts=(TaskAnalysisAttempt(proposal=proposal, admission=admission),),
            accepted=accepted,
        )

    def _analyze_with_model(
        self,
        text: str,
        conversation_messages: list[ConversationMessage] | None = None,
        *,
        feedback: object | None = None,
    ) -> TaskAnalysisProposalBody | None:
        if self._model_client is None:
            return None
        prompt = get_prompt("task_analyzer.system")
        messages = [{"role": "system", "content": prompt.template}]
        for message in conversation_messages or []:
            role = message.get("role")
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        messages.append({
            "role": "user",
            "content": render_prompt("task_analyzer.user", text=text)
            + (
                "\n\n严格按以下 DecisionFeedback 修订。grounding_only 时必须逐字段复现上次"
                "业务提案，只能修改 grounding_claims；semantic_revision 时，user_explicit"
                "字段必须改为用户输入中的逐字片段，否则将 origin 改为 model_inferred。"
                "对 DecisionFeedback.rejected_field_refs 中的 criterion/constraint，优先直接将"
                "origin 改为 model_inferred，并删除对应 grounding_claim；不要再次尝试伪造逐字引用。"
                "output_field_ref 只能使用 goals.0.constraints.0.description 这种点号路径，"
                "禁止方括号路径。\n"
                + json.dumps(
                    feedback.model_dump(mode="json")
                    if isinstance(feedback, BaseModel) else feedback,
                    ensure_ascii=False,
                    default=str,
                )
                if feedback is not None else ""
            ),
        })
        try:
            from personal_agent.capabilities.contracts.model import sealed_context_projection_ref

            response = self._model_client.generate(StructuredModelRequest(
                operation="task_analysis",
                version=prompt.version,
                messages=messages,
                output_type=TaskAnalysisProposalBody,
                context_projection_ref=sealed_context_projection_ref(
                    purpose="task_analysis", messages=messages,
                ),
                temperature=0,
                max_tokens=3000,
            ))
            return response.value
        except Exception:
            logger.exception("Task analysis failed")
            return None

    @staticmethod
    def _log(entry_input: EntryInput, analysis: TaskAnalysis, strategy: str) -> None:
        log_event(
            logger,
            logging.INFO,
            "task_analysis.completed",
            strategy=strategy,
            outcome=analysis.outcome,
            goal_count=len(analysis.goals),
            relation_count=len(analysis.relations),
            result_contracts=[goal.result_contract for goal in analysis.goals],
            user_goal=analysis.user_goal,
            missing_information=analysis.missing_information,
            source_type=entry_input.source_type,
            user_id=entry_input.user_id,
            session_id=entry_input.session_id,
            text_preview=entry_input.text[:120],
        )

    @staticmethod
    def _log_denial(entry_input: EntryInput, proposal, admission) -> None:
        log_event(
            logger,
            logging.WARNING,
            "task_analysis.denied",
            proposal_ref=proposal.proposal_id,
            reason_codes=admission.reason_codes,
            user_id=entry_input.user_id,
            session_id=entry_input.session_id,
        )


def _clarification_body(
    prompt: str,
    missing_information: list[str],
) -> TaskAnalysisProposalBody:
    return TaskAnalysisProposalBody(
        user_goal="理解用户要完成的目标",
        outcome="clarify",
        clarification=ClarificationDraft(
            missing_information=missing_information,
            prompt=prompt,
        ),
    )


def describe_task_analysis(accepted: AcceptedTaskAnalysis | None) -> str:
    if accepted is None:
        return "未提供任务理解结果。"
    analysis = accepted.analysis
    if analysis.error == "analyzer_unavailable":
        return analysis.clarification_prompt
    if analysis.requires_clarification:
        return analysis.clarification_prompt
    if analysis.outcome == "rejected":
        return analysis.rejection_reason
    return "已识别目标：" + "；".join(goal.description for goal in analysis.goals)


def _analysis_text(entry_input: EntryInput) -> str:
    text = entry_input.text.strip()
    if not entry_input.artifacts:
        return text
    artifact_lines = [
        f"- {artifact.filename} ({artifact.source_type}, {artifact.content_type or 'unknown'})"
        for artifact in entry_input.artifacts
    ]
    return (
        f"{text or '用户上传了附件，但没有额外文字说明。'}\n\n"
        "当前请求附带 artifacts：\n" + "\n".join(artifact_lines)
    )


__all__ = [
    "AnalysisOutcome",
    "ClarificationDraft",
    "DefaultTaskAnalyzer",
    "EvidenceRequirement",
    "Goal",
    "GoalDraft",
    "GoalRelation",
    "GoalRelationDraft",
    "RelationKind",
    "RelationOrigin",
    "ResourceHintOrigin",
    "ResourceHint",
    "ResultContract",
    "SideEffectIntent",
    "TaskAnalysis",
    "TaskAnalysisGroundingClaim",
    "TaskAnalysisAttempt",
    "TaskAnalysisProposal",
    "TaskAnalysisProposalBody",
    "TaskAnalysisProvenanceRecord",
    "TaskAnalysisResult",
    "AcceptedTaskAnalysis",
    "SuccessCriterionDraft",
    "GoalConstraintDraft",
    "TaskAnalyzer",
    "describe_task_analysis",
]
