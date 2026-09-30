"""Claim admission and version-bound research checks in the Conversation loop."""
from collections.abc import Generator, Sequence
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.capabilities.contracts.model import StructuredModelRequest
from personal_agent.capabilities.contracts.research import (
    ResearchBasis, ResearchClaim, ResearchClaims,
    ResearchCoverageReport, ResearchReview, ResearchSource, ResearchReopening,
)
from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment, ConversationEvidenceReference, OverreachReport,
)
from personal_agent.capabilities.contracts.model import sealed_context_projection_ref
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompts import get_prompt

from .citations import materialize_cited_draft, materialize_reference_sources, materialize_citation_context
from .context_materialization import materialize_interaction_inputs
from .models import ConversationMessage, InteractionInput


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateClaims(_Strict):
    kind: Literal["create_claims"]
    claims: tuple[ConversationAnswerSegment, ...] = Field(min_length=1)


class _Edit(_Strict):
    base_ref: ResourceRef


class ReviseClaimFragment(_Edit):
    kind: Literal["revise_claim_fragment"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    old_fragment: str = Field(min_length=1)
    replacement: str


class ReplaceClaimReferences(_Edit):
    kind: Literal["replace_claim_references"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    references: tuple[ConversationEvidenceReference, ...]


class AddClaims(_Edit):
    kind: Literal["add_claims"]
    claims: tuple[ConversationAnswerSegment, ...] = Field(min_length=1)


class DeleteClaim(_Edit):
    kind: Literal["delete_claim"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")


class RecheckClaims(_Edit):
    kind: Literal["recheck_claims"]


class ReturnToActions(_Strict):
    kind: Literal["return_to_actions"]
    reason: str = Field(min_length=1)


class StopResearch(_Strict):
    kind: Literal["stop_research"]
    reason: str = Field(min_length=1)


class InitialResearchSubmission(_Strict):
    submission: Annotated[CreateClaims | ReturnToActions | StopResearch, Field(discriminator="kind")]


class ResearchSubmission(_Strict):
    submission: Annotated[
        ReviseClaimFragment | ReplaceClaimReferences | AddClaims | DeleteClaim |
        RecheckClaims | ReturnToActions | StopResearch, Field(discriminator="kind")
    ]


def current_claims(inputs: Sequence[InteractionInput]) -> ResearchClaims | None:
    return next((item for item in reversed(inputs) if isinstance(item, ResearchClaims)), None)


def has_research_source_text(inputs: Sequence[InteractionInput]) -> bool:
    """A real returned source opens research submission, never approval or delivery."""
    return any(item.document_kind == "source_text" and item.citations
               for item in materialize_citation_context(materialize_interaction_inputs(inputs)))


def accepted_basis(inputs: Sequence[InteractionInput]) -> ResearchBasis | None:
    current = current_claims(inputs)
    if current is None:
        return None
    if any(isinstance(item, ResearchReopening) and item.resource_ref == current.resource_ref for item in inputs):
        return None
    latest = next((item for item in reversed(inputs) if isinstance(item, ResearchReview)), None)
    if (latest is None or latest.resource_ref != current.resource_ref
            or not isinstance(latest.report, ResearchCoverageReport) or not latest.report.sufficient):
        return None
    return ResearchBasis(claims=current, sources=_referenced_sources(current, inputs))


def _referenced_sources(current: ResearchClaims, inputs: Sequence[InteractionInput]) -> tuple[ResearchSource, ...]:
    """Project the cited execution source identities without creating another fact owner."""
    return tuple(dict.fromkeys(
        ResearchSource(evidence_id=location.evidence_id, source_url=location.source.source_url)
        for location in materialize_reference_sources(current.claims, inputs)
    ))


def admit_claim_change(action, inputs: Sequence[InteractionInput], initial_ref: ResourceRef) -> ResearchClaims:
    """Only this owner assigns identities and changes exact current claim text."""
    current = current_claims(inputs)
    next_id = 1 + max((int(claim.claim_id[1:]) for item in inputs
                       if isinstance(item, ResearchClaims) for claim in item.claims), default=0)

    def identify(parts):
        return tuple(ResearchClaim(**part.model_dump(), claim_id=f"c{next_id + index}")
                     for index, part in enumerate(parts))

    if isinstance(action, CreateClaims):
        if current is not None:
            raise ValueError("已有集合必须使用当前版本上的局部编辑，不能重新创建。")
        claims = identify(action.claims)
        reference = initial_ref
    else:
        if current is None or action.base_ref != current.resource_ref:
            raise ValueError("base_ref 必须精确匹配当前 research_claims.resource_ref；旧版没有被修改。")
        reference = current.resource_ref.model_copy(update={"revision": current.resource_ref.revision + 1})
        claims = current.claims
        if isinstance(action, AddClaims):
            claims += identify(action.claims)
        elif not isinstance(action, RecheckClaims):
            index = next((i for i, claim in enumerate(claims) if claim.claim_id == action.claim_id), None)
            if index is None:
                raise ValueError("claim_id 不属于当前版本。")
            if isinstance(action, DeleteClaim):
                if len(claims) == 1:
                    raise ValueError("不能删除当前版本的最后一条 claim；需保留至少一条有据论断。")
                claims = claims[:index] + claims[index + 1:]
            elif isinstance(action, ReviseClaimFragment):
                claim = claims[index]
                if claim.text.count(action.old_fragment) != 1:
                    raise ValueError("old_fragment 必须在当前 claim 正文中原样且唯一出现。")
                updated = claim.text.replace(action.old_fragment, action.replacement, 1)
                if not updated.strip():
                    raise ValueError("片段修订不能清空整个 claim。")
                replacements = (ResearchClaim(claim_id=claim.claim_id, text=updated, references=claim.references),)
                claims = claims[:index] + replacements + claims[index + 1:]
            elif isinstance(action, ReplaceClaimReferences):
                claim = claims[index]
                replacements = (ResearchClaim(claim_id=claim.claim_id, text=claim.text, references=action.references),)
                claims = claims[:index] + replacements + claims[index + 1:]
            else:
                raise ValueError("unsupported claim change")
    result = ResearchClaims(resource_ref=reference, claims=claims)
    # Coordinates must bind before any journal mutation or semantic call.
    materialize_cited_draft(result.claims, inputs)
    return result


def research_request(name: str, output_type: type[BaseModel], payload: dict) -> StructuredModelRequest:
    prompt = get_prompt(name)
    messages = [{"role": "system", "content": prompt.template},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    return StructuredModelRequest(
        operation=name.replace(".", "_"), version=prompt.version, messages=messages,
        output_type=output_type, temperature=0, max_tokens=8192,
        context_projection_ref=sealed_context_projection_ref(purpose=name, messages=messages),
        metadata={"component": "conversation_research"},
    )


def verification_steps(
    current: ResearchClaims, inputs: Sequence[InteractionInput], messages: Sequence[ConversationMessage],
) -> Generator[StructuredModelRequest | ResearchReview, BaseModel | None, None]:
    """The runtime drives this sequence and accounts for each real model response."""
    units = materialize_cited_draft(current.claims, inputs)
    for claim, unit in zip(current.claims, units, strict=True):
        report = yield research_request("interaction_verification.cited_support", OverreachReport,
                                        unit.model_dump(mode="json"))
        assert isinstance(report, OverreachReport)
        valid_ids = {evidence.id for evidence in unit.execution_evidence}
        for finding in report.findings:
            if len(set(finding.evidence_ids)) != len(finding.evidence_ids) or not set(finding.evidence_ids).issubset(valid_ids):
                raise ValueError("research support finding must reference only submitted evidence")
        yield ResearchReview(resource_ref=current.resource_ref, claim_id=claim.claim_id,
                             report=report)
        if report.findings:
            return
    report = yield research_request("conversation.research.coverage", ResearchCoverageReport, {
        "conversation": [message.model_dump(mode="json") for message in messages],
        "claims": current.model_dump(mode="json"),
    })
    assert isinstance(report, ResearchCoverageReport)
    yield ResearchReview(resource_ref=current.resource_ref, report=report)
