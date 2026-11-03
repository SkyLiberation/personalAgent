"""Semantic verification contracts shared by the verifier tool and admission.

The tool that produces a receipt lives in ``personal_agent.tools``; the
admission that consumes one lives in ``personal_agent.application``. The
explicit package DAG forbids ``application -> tools``, so the receipt type has
to live in a package both may depend on. Keeping it here is what lets admission
parse a receipt into its declared type instead of reading an untyped ``dict``:
a renamed field then fails loudly at the boundary rather than degrading into a
silent ``None`` that no caller can distinguish from a real mismatch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic import model_validator

from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

VerificationVerdict = Literal["passed", "failed"]
VerificationKind = Literal["goal", "answer"]


class ConversationEvidenceReference(BaseModel):
    """A writer's reference to an exact returned document coordinate."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str = Field(
        pattern=r"^d[1-9][0-9]*:[1-9][0-9]*(?:-[1-9][0-9]*|:[1-9][0-9]*-[1-9][0-9]*)?$",
        description="使用已返回的文档号:行号（d2:37）；同一文档已完整返回的连续多行可合并为 d2:37-40，含首尾且结束行大于起始行，中间不能缺行。部分行仅原样复制实际返回的字符范围（d2:37:1-80），不能扩大。非连续行或不同文档分别引用；网页正文与工具结果统一使用本格式。",
    )


class ConversationAnswerSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=1, description="本段直接交付给用户的正文，不是来源摘录或正文定位副本。")
    references: tuple[ConversationEvidenceReference, ...] = ()


class CitationSource(BaseModel):
    """Execution-owned document snapshot and position, never writer-supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef | None = None
    content_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    document_kind: Literal["source_text", "tool_result"] = "source_text"
    source_url: str | None
    line: int = Field(ge=1)
    start_column: int = Field(ge=1)

    @model_validator(mode="after")
    def _one_document_identity(self):
        if (self.resource_ref is None) == (self.content_digest is None):
            raise ValueError("citation source requires exactly one resource version or inline content digest")
        return self


class CitedEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(min_length=1)
    text: str
    source: CitationSource | None = None


class CitedDraftUnit(BaseModel):
    """Request-local exact draft text and all of its writer-submitted evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    draft: str = Field(min_length=1)
    execution_evidence: tuple[CitedEvidence, ...] = ()


class OverreachFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    evidence_ids: tuple[str, ...]
    exceeded_scope: str = Field(min_length=1)


class OverreachReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    findings: tuple[OverreachFinding, ...]


class CitedSupportRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["cited_support_rejection"] = "cited_support_rejection"
    rejected_draft: str
    checked_draft: str = Field(min_length=1)
    findings: tuple[OverreachFinding, ...] = Field(min_length=1)
    explanation: str = (
        DEFAULT_PROMPTS.get('verification.cited_support_rejection.explanation').template
    )


class SourceReadingState(BaseModel):
    """Request-local coverage derived from visible, version-bound execution facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef
    source_url: str
    returned_unique_segments: int = Field(ge=0)
    total_segments: int | None = Field(ge=0)
    fully_read: bool

    @model_validator(mode="after")
    def check_coverage(self):
        if self.total_segments is not None and self.returned_unique_segments > self.total_segments:
            raise ValueError("returned segments exceed source length")
        complete = bool(self.total_segments) and self.returned_unique_segments == self.total_segments
        if self.fully_read != complete:
            raise ValueError("fully_read must be derived from nonempty source coverage")
        return self


class VerificationCriterion(BaseModel):
    """Request-local reference to an unchanged runtime-owned criterion."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")
    criterion: str = Field(min_length=1)


class VerificationCriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(
        pattern=r"^r[1-9][0-9]*$",
        description="引用本次 success_criteria 中的 criterion_id；原文由 Runtime 恢复，不返回 criterion 正文。",
    )
    status: Literal["satisfied", "not_satisfied", "insufficient_evidence"]
    feedback: str = ""


class BoundVerificationCriterionResult(VerificationCriterionResult):
    """A judgment with the exact criterion restored by its runtime owner."""

    criterion: str = Field(min_length=1)


class SemanticVerificationReport(BaseModel):
    """Judgments for user criteria and the verifier-owned source-support criterion.

    This is the verifier's ``output_type``, so the model owns all of it. It
    deliberately carries no aggregate verdict, receipt identity, or digest: anything a
    later admission decision can derive from these judgments is computed by the
    tool, never proposed redundantly by the model.
    """

    model_config = ConfigDict(extra="forbid")

    criterion_results: tuple[VerificationCriterionResult, ...] = Field(min_length=1)
    revision_feedback: str = ""


class UserRequirementCheck(BaseModel):
    """One correctable comparison of a user requirement with the submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement: str = Field(
        min_length=1, pattern=r"\S",
        description="本轮实际适用的一项用户要求，写清对象及所要求的关系；依据原始用户消息及仍有效历史，不将模型自己的定义当作用户要求。",
    )
    status: Literal["satisfied", "not_satisfied", "insufficient_evidence"] = Field(
        description="本项要求的判决：满足为 satisfied，明确遗漏或冲突为 not_satisfied，缺少不可替代前提而无法判断为 insufficient_evidence。",
    )
    feedback: str = Field(
        min_length=1, pattern=r"\S",
        description="本次待验内容怎样对应这一要求；有差异时指出实际偏离及需要修订的部分，不代写替代内容。",
    )


class UserRequirementAssessment(BaseModel):
    """Requirement-level judgments, consumed by the runtime verifier adapter."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    checks: tuple[UserRequirementCheck, ...] = Field(
        min_length=1,
        description="JSON 对象数组，每项包含 requirement、status、feedback；逐项覆盖影响本轮交付的用户要求，至少一项，不能用字符串数组、单对象、null 或空数组替代。",
    )


class SemanticVerificationReceipt(SemanticVerificationReport):
    """A report plus the tool-computed facts an admission may rely on.

    ``receipt_id`` is derived from ``draft_digest``, so referencing an id is
    equivalent to referencing an exact draft and the model cannot fabricate a
    reference to text that was never verified.

    ``success_criteria`` is the preimage of ``criteria_digest``. Carrying it is
    what makes a criteria-drift rejection repairable: the caller is told the
    exact criteria to re-verify against instead of being asked to reproduce
    bytes it no longer has. It also gives the digest an auditable preimage in the
    journal rather than an unverifiable hash.

    User criteria remain unchanged here. ``criterion_results`` additionally
    contains the mandatory verifier-owned source-support judgment; the tool
    checks its presence and includes it in the aggregate verdict. It is not a
    user-authored requirement and does not alter the frozen user criteria.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_results: tuple[BoundVerificationCriterionResult, ...] = Field(min_length=1)
    checked_kind: VerificationKind
    verdict: VerificationVerdict
    receipt_id: str = Field(pattern=r"^svr_[0-9a-f]{20}$")
    verified_draft: str = Field(min_length=1, max_length=20_000)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    success_criteria: tuple[str, ...] = Field(min_length=1)
    criteria_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class VerificationEvent(BaseModel):
    """One actual submission and its verdict, projected from the Journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: VerificationKind
    submission_id: str = Field(min_length=1)
    content: str = Field(min_length=1, max_length=20_000)
    disposition: Literal["answer", "clarification_required", "limitation", "failed"] | None = None
    verdict: SemanticVerificationReceipt | None = None

    @model_validator(mode="after")
    def _paired_verdict(self):
        if (self.kind == "answer") != (self.disposition is not None):
            raise ValueError("only answer events carry the original disposition")
        if self.verdict is not None and (self.verdict.checked_kind != self.kind
                or self.verdict.verified_draft != self.content):
            raise ValueError("verification verdict belongs to another submission")
        return self


class VerificationTurn(BaseModel):
    """A user's original question and its time-ordered verification history."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    user_turn: int = Field(ge=1)
    question: str = Field(min_length=1)
    events: tuple[VerificationEvent, ...]
    summary: str | None = None


class VerificationContext(BaseModel):
    """One responsibility's history; the last event is its current submission."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: VerificationKind
    turns: tuple[VerificationTurn, ...] = Field(min_length=1)
    active_goal: str | None = None
    binding: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _turn_order(self):
        if tuple(item.user_turn for item in self.turns) != tuple(range(1, len(self.turns) + 1)):
            raise ValueError("verification history must follow user-question order")
        if any(event.kind != self.kind for turn in self.turns for event in turn.events):
            raise ValueError("verification history contains another responsibility's events")
        if not self.turns[-1].events or self.turns[-1].events[-1].verdict is not None:
            raise ValueError("the current submission must await this verification")
        return self


__all__ = [
    "VerificationContext",
    "VerificationEvent",
    "VerificationTurn",
    "VerificationKind",
    "BoundVerificationCriterionResult",
    "SemanticVerificationReceipt",
    "SemanticVerificationReport",
    "UserRequirementAssessment",
    "UserRequirementCheck",
    "VerificationCriterionResult",
    "VerificationCriterion",
    "VerificationVerdict",
]
