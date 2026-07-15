"""Semantic task understanding without execution routing or capability selection."""

from __future__ import annotations

import logging
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.infra.structured_model import StructuredModelClient, StructuredModelRequest
from personal_agent.kernel.contracts.capability import CapabilityOperation
from personal_agent.kernel.logging_utils import log_event
from personal_agent.kernel.models import EntryInput
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
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
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


class TaskAnalysisOutput(BaseModel):
    """Structured model DTO for task understanding."""

    user_goal: str = Field(min_length=1)
    outcome: AnalysisOutcome
    goals: list[GoalDraft] = Field(default_factory=list)
    relations: list[GoalRelationDraft] = Field(default_factory=list)
    clarification: ClarificationDraft | None = None
    rejection_reason: str | None = None
    direct_answer: str = ""

    @model_validator(mode="after")
    def _validate_contract(self) -> "TaskAnalysisOutput":
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
            if self.direct_answer:
                if len(self.goals) != 1:
                    raise ValueError("direct_answer requires exactly one response goal")
                goal = self.goals[0]
                if (
                    goal.result_contract != "response"
                    or goal.resource_hints
                    or goal.side_effect_intent != "none"
                    or goal.evidence_requirement is not None
                ):
                    raise ValueError("direct_answer requires an ungrounded response result")
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
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
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

    user_goal: str = ""
    outcome: AnalysisOutcome = "ready"
    goals: list[Goal] = Field(default_factory=list)
    relations: list[GoalRelation] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    clarification_prompt: str = ""
    rejection_reason: str = ""
    error: Literal["analyzer_unavailable"] | None = None
    direct_answer: str = ""

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


class TaskAnalyzer(Protocol):
    def analyze(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> TaskAnalysis: ...


class DefaultTaskAnalyzer:
    """Use semantic model understanding; deterministic code handles structure only."""

    def __init__(self, model_client: StructuredModelClient | None) -> None:
        self._model_client = model_client

    def analyze(
        self,
        entry_input: EntryInput,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> TaskAnalysis:
        if not entry_input.text.strip() and not entry_input.artifacts:
            analysis = _clarification(
                "请补充你想完成的具体目标。",
                ["明确的目标、问题或操作对象"],
            )
            self._log(entry_input, analysis, "structural_empty")
            return analysis

        output = self._analyze_with_model(
            _analysis_text(entry_input),
            conversation_messages or [],
        )
        if output is None:
            analysis = _clarification(
                "任务理解模型当前不可用，无法可靠推断目标和操作边界。请稍后重试。",
                ["可用的任务理解模型"],
                error="analyzer_unavailable",
            )
            self._log(entry_input, analysis, "analyzer_unavailable")
            return analysis

        analysis = _to_analysis(output)
        self._log(entry_input, analysis, "semantic_model")
        return analysis

    def _analyze_with_model(
        self,
        text: str,
        conversation_messages: list[ConversationMessage] | None = None,
    ) -> TaskAnalysisOutput | None:
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
            "content": render_prompt("task_analyzer.user", text=text),
        })
        try:
            response = self._model_client.generate(StructuredModelRequest(
                operation="task_analysis",
                version=prompt.version,
                messages=messages,
                output_type=TaskAnalysisOutput,
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


def _to_analysis(output: TaskAnalysisOutput) -> TaskAnalysis:
    clarification = output.clarification
    goals = [Goal(
        goal_id=f"goal_{index}",
        description=draft.description,
        result_contract=draft.result_contract,
        success_criteria=draft.success_criteria,
        constraints=draft.constraints,
        side_effect_intent=draft.side_effect_intent,
        evidence_requirement=draft.evidence_requirement,
        resource_hints=draft.resource_hints,
    ) for index, draft in enumerate(output.goals, start=1)]
    return TaskAnalysis(
        user_goal=output.user_goal,
        outcome=output.outcome,
        goals=goals,
        relations=[GoalRelation(
            predecessor_goal_id=f"goal_{relation.predecessor}",
            successor_goal_id=f"goal_{relation.successor}",
            kind=relation.kind,
            origin=relation.origin,
            rationale=relation.rationale,
        ) for relation in output.relations],
        missing_information=clarification.missing_information if clarification else [],
        clarification_prompt=clarification.prompt if clarification else "",
        rejection_reason=output.rejection_reason or "",
        direct_answer=output.direct_answer,
    )


def _clarification(
    prompt: str,
    missing_information: list[str],
    *,
    error: Literal["analyzer_unavailable"] | None = None,
) -> TaskAnalysis:
    return TaskAnalysis(
        user_goal="理解用户要完成的目标",
        outcome="clarify",
        missing_information=missing_information,
        clarification_prompt=prompt,
        error=error,
    )


def describe_task_analysis(analysis: TaskAnalysis | None) -> str:
    if analysis is None:
        return "未提供任务理解结果。"
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
    "TaskAnalysisOutput",
    "TaskAnalyzer",
    "describe_task_analysis",
]
