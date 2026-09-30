"""Immutable claims and model-owned research judgments for Conversation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment, OverreachReport,
    SemanticVerificationReport,
)
from personal_agent.kernel.contracts.resource import ResourceRef


class ResearchClaim(ConversationAnswerSegment):
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")


class ResearchClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_claims"] = "research_claims"
    resource_ref: ResourceRef
    claims: tuple[ResearchClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_identity(self):
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim identities must be unique")
        return self


class ResearchCoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    sufficient: StrictBool
    missing_facts: tuple[str, ...]
    feedback: str

    @model_validator(mode="after")
    def consistent(self):
        if self.sufficient and self.missing_facts:
            raise ValueError("sufficient research cannot have missing facts")
        if not self.sufficient and not (self.missing_facts or self.feedback.strip()):
            raise ValueError("insufficient research requires feedback")
        return self


class ResearchReview(BaseModel):
    """One exact-version judgment; coverage is reached only after all local checks."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_review"] = "research_review"
    resource_ref: ResourceRef
    claim_id: str | None = None
    report: OverreachReport | ResearchCoverageReport


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    source_url: str | None


class ResearchBasis(BaseModel):
    """Runtime projection of an accepted revision, never a model-authored approval."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    claims: ResearchClaims
    sources: tuple[ResearchSource, ...]


class ResearchFinalReport(SemanticVerificationReport):
    research_feedback: str = Field(description="仅研究事实缺口时说明缺失内容；汇总表达或排版问题为空。")

    @model_validator(mode="after")
    def gap_requires_rejection(self):
        if self.research_feedback.strip() and all(item.status == "satisfied" for item in self.criterion_results):
            raise ValueError("a research gap cannot accompany a passed final report")
        return self


class ResearchReopening(BaseModel):
    """A final verifier's fact-gap feedback returns the exact basis to its writer."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_reopening"] = "research_reopening"
    resource_ref: ResourceRef
    feedback: str = Field(min_length=1)
