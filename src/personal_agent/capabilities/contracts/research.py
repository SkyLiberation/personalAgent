"""Immutable claims and model-owned research judgments for Conversation."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS


class ResearchClaimContent(ConversationAnswerSegment):
    text: str = Field(
        min_length=1,
        description="研究论断正文，作为最终回答的事实依据；最终文章由同一研究版本的 final_answer 保存。",
    )


class ResearchClaim(ResearchClaimContent):
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")


class ResearchClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_claims"] = "research_claims"
    resource_ref: ResourceRef
    claims: tuple[ResearchClaim, ...] = Field(min_length=1)
    final_answer: tuple[ConversationAnswerSegment, ...] | None = None

    @model_validator(mode="after")
    def unique_identity(self):
        if len({claim.claim_id for claim in self.claims}) != len(self.claims):
            raise ValueError("claim identities must be unique")
        return self


ResearchSupportCategory = Literal[
    "citation_not_supported", "factual_conflict", "source_attribution_conflict",
    "normative_status_conflict", "obligation_strength_conflict",
    "evidence_presence_conflict", "requirement_not_satisfied", "answer_claim_mismatch",
]


class ResearchClaimSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    end_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")


class ResearchRequirementTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")


class ResearchAnswerTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    answer_segment_id: str = Field(pattern=r"^a[1-9][0-9]*$")


class ResearchSupportFinding(BaseModel):
    """One model-owned error classification bound to the submitted source input."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: ResearchSupportCategory
    target: ResearchClaimSpan | ResearchRequirementTarget | ResearchAnswerTarget
    error_description: str = Field(min_length=1)
    evidence_ids: tuple[str, ...]

    @model_validator(mode="after")
    def target_matches_category(self, info: ValidationInfo):
        prompts = info.context if isinstance(info.context, PromptCatalog) else DEFAULT_PROMPTS
        goal_gap = self.category == "requirement_not_satisfied"
        if goal_gap != isinstance(self.target, ResearchRequirementTarget):
            raise ValueError(prompts.render('research_validation.target_category'))
        return self


class ResearchSupportReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    findings: tuple[ResearchSupportFinding, ...]


class ResearchReview(BaseModel):
    """A completed judgment bound to its original input, never a copied approval."""
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["research_review"] = "research_review"
    resource_ref: ResourceRef
    report: ResearchSupportReport
    source_prompt_version: str = Field(min_length=1)
