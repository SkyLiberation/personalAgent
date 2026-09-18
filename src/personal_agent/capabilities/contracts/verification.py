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

from pydantic import BaseModel, ConfigDict, Field, StrictBool
from pydantic import model_validator

from personal_agent.kernel.contracts.resource import ResourceRef

VerificationVerdict = Literal["passed", "failed"]


class ConversationEvidenceReference(BaseModel):
    """A writer's reference to a visible execution, optionally one returned line."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str = Field(min_length=1, description="原样复制当前可见证据旁的 evidence_id（如 e7），不生成调用标识、行号或偏移。")


class ConversationAnswerSegment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    text: str = Field(min_length=1, description="本段直接交付给用户的正文，不是来源摘录或正文定位副本。")
    references: tuple[ConversationEvidenceReference, ...] = ()


class EvidenceSufficiencyAssessment(BaseModel):
    """Writer decision to end research for this submission, never source evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)
    reason: str = Field(
        min_length=1, max_length=2_000,
        description="现有证据足以支持本次完整回答的理由；这是结束取证的判断，不是事实证据。",
    )


class CitationSource(BaseModel):
    """Execution-owned location of a cited read window, never writer-supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef
    source_url: str | None
    line: int = Field(ge=1)
    start_column: int = Field(ge=1)


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
        "本次提交的证据不足以支持所列草稿声明，暂不交付。"
        "这不证明原文没有依据或声明必然为假。请补充已有引用、继续取证或修订结论后重新提交；"
        "补充引用时可以保留有据的原稿，不必为了改稿而改变事实。"
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


class DocumentAbsenceReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    absence_by_source: tuple[StrictBool, ...] = Field(
        description="与输入 source_reading_state 等长同序；每项表示稿件是否对该来源作出了文档级缺项声明，不判断原文是否确实缺项或应否拒绝。",
    )


class SourceCoverageRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["source_coverage_rejection"] = "source_coverage_rejection"
    rejected_draft: str
    unread_sources: tuple[SourceReadingState, ...] = Field(min_length=1)


def reject_unread_document_absence(
    draft: str,
    classification: DocumentAbsenceReport,
    states: tuple[SourceReadingState, ...],
) -> SourceCoverageRejection | None:
    """Validate binding, then enforce coverage independently of semantic support."""
    if len({state.resource_ref for state in states}) != len(states):
        raise ValueError("duplicate source reading state")
    if len(classification.absence_by_source) != len(states):
        raise ValueError("absence_by_source must have exactly one boolean per source_reading_state entry")
    rejected = tuple(
        state for is_absence, state in zip(classification.absence_by_source, states, strict=True)
        if is_absence and not state.fully_read
    )
    if not rejected:
        return None
    return SourceCoverageRejection(
        rejected_draft=draft, unread_sources=rejected,
    )


class VerificationCriterionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    criterion: str
    status: Literal["satisfied", "not_satisfied", "insufficient_evidence"]
    feedback: str = ""


class SemanticVerificationReport(BaseModel):
    """Judgments for user criteria and the verifier-owned source-support criterion.

    This is the verifier's ``output_type``, so the model owns all of it. It
    deliberately carries no aggregate verdict, identity, or digest: anything a
    later admission decision can derive from these judgments is computed by the
    tool, never proposed redundantly by the model.
    """

    model_config = ConfigDict(extra="forbid")

    criterion_results: tuple[VerificationCriterionResult, ...] = Field(min_length=1)
    revision_feedback: str = ""


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

    verdict: VerificationVerdict
    receipt_id: str = Field(pattern=r"^svr_[0-9a-f]{20}$")
    verified_draft: str = Field(min_length=1, max_length=20_000)
    draft_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    success_criteria: tuple[str, ...] = Field(min_length=1)
    criteria_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


__all__ = [
    "SemanticVerificationReceipt",
    "SemanticVerificationReport",
    "VerificationCriterionResult",
    "VerificationVerdict",
]
