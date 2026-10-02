"""Immutable claims and model-owned research judgments for Conversation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment,
    ConversationEvidenceReference,
    SemanticVerificationReport,
)
from personal_agent.kernel.contracts.resource import ResourceRef


class ResearchClaimContent(ConversationAnswerSegment):
    text: str = Field(
        min_length=1,
        description="仅供研究来源核验与独立汇总使用的论断正文；不是直接交付用户的最终文章。",
    )


class ResearchClaim(ResearchClaimContent):
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


class ResearchRequirementCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$", description="沿用冻结 requirements 中的原验收编号。")
    requirement: str = Field(min_length=1, description="该原项要求回答的最小事实关系，按用户目标确定，不从草稿或资料新增目标。")
    claim_ids: tuple[str, ...] = Field(description="已回答或仍需补充该问题的当前 claim 身份；尚无对应项时为空。")
    status: Literal["covered", "missing", "needs_evidence", "delivery_check"]
    references: tuple[ConversationEvidenceReference, ...] = Field(
        default=(), description="与必要事实、遗漏或未知边界相关的实际返回原文坐标；未取得对应原文时为空。",
    )
    feedback: str = Field(min_length=1, description="说明当前事实如何满足问题，或指出具体缺失事实及取证边界。")

    @model_validator(mode="after")
    def covered_requires_claims(self):
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("coverage must reference each current claim at most once")
        if self.status == "covered" and not self.claim_ids:
            raise ValueError("covered user requirement must identify its research claims")
        return self


class ResearchCoverageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirements: tuple[ResearchRequirementCoverage, ...] = Field(min_length=1)

    @property
    def sufficient(self) -> bool:
        return all(item.status in {"covered", "delivery_check"} for item in self.requirements)


class ResearchSupportFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    end_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    unsupported_assertion: str = Field(min_length=1)
    supported_scope: str = Field(min_length=1)
    missing_premise: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]


class ResearchSupportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    findings: tuple[ResearchSupportFinding, ...]


class ResearchReview(BaseModel):
    """A completed judgment bound to its original input, never a copied approval."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_review"] = "research_review"
    resource_ref: ResourceRef
    claim_id: str | None = None
    report: ResearchSupportReport | ResearchCoverageReport
    source_prompt_version: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def judgment_identity(self):
        if isinstance(self.report, ResearchSupportReport):
            if self.claim_id is None or self.source_prompt_version is None:
                raise ValueError("source judgment requires claim and prompt version")
        elif self.claim_id is not None or self.source_prompt_version is not None:
            raise ValueError("coverage judgment binds the complete revision")
        return self


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
