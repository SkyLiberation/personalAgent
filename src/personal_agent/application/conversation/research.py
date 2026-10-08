"""Claim admission and version-bound research checks in the Conversation loop."""
from collections.abc import Generator, Sequence
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personal_agent.capabilities.contracts.model import StructuredModelRequest
from personal_agent.capabilities.contracts.research import (
    ResearchBasis, ResearchClaim, ResearchClaimContent, ResearchClaims,
    ResearchCoverageReport, ResearchReview, ResearchSource, ResearchReopening,
    ResearchSupportReport,
)
from personal_agent.capabilities.contracts.verification import (
    ConversationAnswerSegment, ConversationEvidenceReference, CitedDraftUnit, CitedEvidence,
)
from personal_agent.capabilities.contracts.model import sealed_context_projection_ref
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompts import get_prompt

from .citations import CitableInput, materialize_cited_draft, materialize_reference_sources, materialize_citation_context, selected_citation_ids
from .context_materialization import materialize_interaction_inputs
from .models import ActionObservation, ConversationMessage, InteractionInput, ReviewCriteria
from .source_reading import materialize_source_reading_state


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchGoalRequirement(_Strict):
    """Read-only identity projection of the frozen interaction requirements."""

    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")
    criterion: str


def research_goal_requirements(criteria: ReviewCriteria) -> tuple[ResearchGoalRequirement, ...]:
    return tuple(ResearchGoalRequirement(criterion_id=f"r{index}", criterion=criterion)
                 for index, criterion in enumerate(criteria.criteria, start=1))


class ResearchInformationNeed(_Strict):
    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")
    question: str = Field(min_length=1)
    status: Literal["answered", "ready", "needs_evidence", "delivery_check"]
    claim_ids: tuple[str, ...] = ()
    references: tuple[ConversationEvidenceReference, ...] = ()
    fit_reason: str = ""
    gap: str = ""

    @model_validator(mode="after")
    def account_for_answer_or_gap(self) -> Self:
        if self.status == "answered" and not self.claim_ids:
            raise ValueError("answered research requirement must identify current claims")
        if self.status == "needs_evidence" and not self.gap.strip():
            raise ValueError("research evidence gap must explain the necessary missing information")
        if len(set(self.claim_ids)) != len(self.claim_ids):
            raise ValueError("research requirement must not repeat claim identities")
        return self


class ResearchEvidenceSelection(_Strict):
    next_step: Literal["write", "acquire", "limit"]
    needs: tuple[ResearchInformationNeed, ...] = Field(min_length=1)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def write_requires_selected_evidence(self) -> Self:
        if self.next_step == "write" and not any(need.references for need in self.needs):
            raise ValueError("writing research claims requires selected returned evidence")
        return self

    @property
    def references(self) -> tuple[ConversationEvidenceReference, ...]:
        return tuple(reference for need in self.needs for reference in need.references)


def validate_research_selection(
    selection: ResearchEvidenceSelection, criteria: ReviewCriteria, current: ResearchClaims | None,
) -> None:
    """Own exact goal accounting; semantic sufficiency remains model-owned."""
    expected = {item.criterion_id for item in research_goal_requirements(criteria)}
    actual = [need.criterion_id for need in selection.needs]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("research selection must account for every frozen criterion exactly once; "
                         f"expected={sorted(expected)}, actual={actual}")
    claim_ids = {claim.claim_id for claim in current.claims} if current else set()
    if any(not set(need.claim_ids).issubset(claim_ids) for need in selection.needs):
        raise ValueError("research selection must identify only current claims")


class CreateClaims(_Strict):
    kind: Literal["create_claims"]
    claims: tuple[ResearchClaimContent, ...] = Field(min_length=1)


class _Edit(_Strict):
    base_ref: ResourceRef


class ReviseClaimFragment(_Edit):
    kind: Literal["revise_claim_fragment"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    start_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    end_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    replacement: str


class ReplaceClaimReferences(_Edit):
    kind: Literal["replace_claim_references"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    references: tuple[ConversationEvidenceReference, ...]


class AddClaims(_Edit):
    kind: Literal["add_claims"]
    claims: tuple[ResearchClaimContent, ...] = Field(min_length=1)


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


class EditableClaimFragment(_Strict):
    fragment_id: str
    text: str
    start: int = Field(exclude=True)
    end: int = Field(exclude=True)


class EditableClaim(_Strict):
    claim_id: str
    fragments: tuple[EditableClaimFragment, ...]
    references: tuple[ConversationEvidenceReference, ...]


class EditableResearchClaims(_Strict):
    kind: Literal["research_claims"] = "research_claims"
    resource_ref: ResourceRef
    claims: tuple[EditableClaim, ...]


def editable_claim_fragments(claim: ResearchClaim) -> tuple[EditableClaimFragment, ...]:
    """Derive lossless, request-local addresses from canonical Python text."""
    delimiters = frozenset("。！？；\r\n")
    text = claim.text
    ranges: list[tuple[int, int]] = []
    start = 0
    index = 0
    while index < len(text):
        if text[index] in delimiters:
            index += 1
            while index < len(text) and text[index] in delimiters:
                index += 1
            ranges.append((start, index))
            start = index
        else:
            index += 1
    if start < len(text):
        ranges.append((start, len(text)))
    fragments = tuple(EditableClaimFragment(
        fragment_id=f"{claim.claim_id}.f{number}",
        text=text[start:end], start=start, end=end,
    ) for number, (start, end) in enumerate(ranges, 1))
    assert fragments and "".join(fragment.text for fragment in fragments) == text
    return fragments


def editable_research_claims(current: ResearchClaims) -> EditableResearchClaims:
    return EditableResearchClaims(resource_ref=current.resource_ref, claims=tuple(
        EditableClaim(claim_id=claim.claim_id, fragments=editable_claim_fragments(claim),
                      references=claim.references)
        for claim in current.claims
    ))


class ResearchDocumentBounds(_Strict):
    document_id: str
    full_line_ranges: tuple[str, ...]
    partial_line_coordinates: tuple[str, ...]


def research_submission_type(
    current: ResearchClaims | None, inputs: Sequence[CitableInput],
) -> type[InitialResearchSubmission] | type[ResearchSubmission]:
    """Project the current argument scope into the Provider's JSON Schema.

    Admission remains the sole owner of binding. The scoped type inherits the
    canonical submission contract and adds no stored or model-authored facts.
    """
    coordinates = {citation.evidence_id for item in inputs for citation in item.citations}
    documents = sorted({coordinate.split(":")[0] for coordinate in coordinates}, key=lambda value: int(value[1:]))
    bounds = []
    for document in documents:
        lines = sorted(int(value.split(":")[1]) for value in coordinates
                       if value.split(":")[0] == document and value.count(":") == 1)
        spans: list[tuple[int, int]] = []
        for line in lines:
            if spans and spans[-1][1] + 1 == line:
                spans[-1] = (spans[-1][0], line)
            else:
                spans.append((line, line))
        bounds.append(ResearchDocumentBounds(
            document_id=document,
            full_line_ranges=tuple(f"{document}:{start}" if start == end else f"{document}:{start}-{end}"
                                   for start, end in spans),
            partial_line_coordinates=tuple(sorted(value for value in coordinates
                                                  if value.split(":")[0] == document and value.count(":") == 2)),
        ))
    claim_ids = [claim.claim_id for claim in current.claims] if current else []
    fragment_ids = [fragment.fragment_id for claim in current.claims
                    for fragment in editable_claim_fragments(claim)] if current else []
    base = InitialResearchSubmission if current is None else ResearchSubmission

    class ScopedResearchSubmission(base):
        @classmethod
        def model_json_schema(cls, **kwargs):
            schema = super().model_json_schema(**kwargs)
            definitions = schema["$defs"]
            for name in ("ReviseClaimFragment", "ReplaceClaimReferences", "DeleteClaim"):
                if name in definitions:
                    definitions[name]["properties"]["claim_id"]["enum"] = claim_ids
            if "ReviseClaimFragment" in definitions:
                for field in ("start_fragment_id", "end_fragment_id"):
                    definitions["ReviseClaimFragment"]["properties"][field]["enum"] = fragment_ids
            reference = definitions["ConversationEvidenceReference"]["properties"]["evidence_id"]
            docs = "|".join(documents)
            reference["pattern"] = (rf"^(?:{docs}):[1-9][0-9]*(?:-[1-9][0-9]*|:[1-9][0-9]*-[1-9][0-9]*)?$"
                                    if docs else r"^(?!)$")
            reference["description"] = (
                "可见坐标来自本轮选择及当前集合已绑定引用。创建和增补只用本轮选择；替换引用可保留目标 claim 的已有坐标，新增坐标须本轮选中。完整行可选同一连续范围内的单行或子区间，不能跨缺行；"
                "部分行只用原样坐标。当前范围："
                + json.dumps([bound.model_dump(mode="json") for bound in bounds], ensure_ascii=False)
            )
            return schema

    return ScopedResearchSubmission


def current_claims(inputs: Sequence[InteractionInput]) -> ResearchClaims | None:
    return next((item for item in reversed(inputs) if isinstance(item, ResearchClaims)), None)


def has_research_source_text(inputs: Sequence[InteractionInput]) -> bool:
    """A real returned source opens research submission, never approval or delivery."""
    return any(item.document_kind == "source_text" and item.citations
               for item in materialize_citation_context(materialize_interaction_inputs(inputs)))


def in_research_mode(
    inputs: Sequence[InteractionInput], *, finalization_mode: bool, requires_review: bool,
) -> bool:
    return finalization_mode and accepted_basis(inputs) is None and (
        current_claims(inputs) is not None or (requires_review and any(
            isinstance(item, ActionObservation) and item.status == "succeeded"
            and item.capability_id in {"web_search", "web_read"} for item in inputs
        ))
    )


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


def admit_claim_change(
    action: CreateClaims | ReviseClaimFragment | ReplaceClaimReferences | AddClaims | DeleteClaim | RecheckClaims,
    inputs: Sequence[InteractionInput], initial_ref: ResourceRef,
    selected_ids: frozenset[str],
) -> ResearchClaims:
    """Only this owner assigns identities and changes exact current claim text."""
    current = current_claims(inputs)
    next_id = 1 + max((int(claim.claim_id[1:]) for item in inputs
                       if isinstance(item, ResearchClaims) for claim in item.claims), default=0)

    def identify(parts: tuple[ResearchClaimContent, ...]) -> tuple[ResearchClaim, ...]:
        return tuple(ResearchClaim(**part.model_dump(), claim_id=f"c{next_id + index}")
                     for index, part in enumerate(parts))

    def require_selected(
        parts: tuple[ConversationAnswerSegment, ...],
        inherited_ids: frozenset[str] = frozenset(),
    ) -> None:
        for part in parts:
            unselected = selected_citation_ids(part.references, inputs) - inherited_ids - selected_ids
            if unselected:
                raise ValueError(f"研究论断新增引用必须来自本轮选中的可见证据坐标；本轮未选坐标：{', '.join(sorted(unselected))}。")

    if isinstance(action, CreateClaims):
        if current is not None:
            raise ValueError("已有集合必须使用当前版本上的局部编辑，不能重新创建。")
        require_selected(action.claims)
        claims = identify(action.claims)
        reference = initial_ref
    else:
        if current is None or action.base_ref != current.resource_ref:
            raise ValueError("base_ref 必须精确匹配当前 research_claims.resource_ref；旧版没有被修改。")
        reference = current.resource_ref.model_copy(update={"revision": current.resource_ref.revision + 1})
        claims = current.claims
        if isinstance(action, AddClaims):
            require_selected(action.claims)
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
                fragments = {fragment.fragment_id: fragment for fragment in editable_claim_fragments(claim)}
                start = fragments.get(action.start_fragment_id)
                end = fragments.get(action.end_fragment_id)
                if start is None or end is None or start.start > end.start:
                    raise ValueError("两个片段 ID 必须属于当前 claim 的可见片段，且起点不得晚于终点；当前版本保持不变。")
                updated = claim.text[:start.start] + action.replacement + claim.text[end.end:]
                if not updated.strip():
                    raise ValueError("片段修订不能清空整个 claim。")
                replacements = (ResearchClaim(claim_id=claim.claim_id, text=updated, references=claim.references),)
                claims = claims[:index] + replacements + claims[index + 1:]
            elif isinstance(action, ReplaceClaimReferences):
                claim = claims[index]
                require_selected(
                    (claim.model_copy(update={"references": action.references}),),
                    selected_citation_ids(claim.references, inputs),
                )
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
        output_type=output_type, temperature=0,
        context_projection_ref=sealed_context_projection_ref(purpose=name, messages=messages),
        metadata={"component": "conversation_research"},
    )


def _applicable_source_review(
    current: ResearchClaims, claim: ResearchClaim, unit: CitedDraftUnit,
    inputs: Sequence[InteractionInput], reuse_start_index: int,
) -> ResearchReview | None:
    """Reuse only the latest equal-input fact within this model binding lifetime."""
    version = get_prompt("conversation.research.support").version
    for index in range(len(inputs) - 1, reuse_start_index - 1, -1):
        review = inputs[index]
        if (not isinstance(review, ResearchReview) or review.claim_id != claim.claim_id
                or not isinstance(review.report, ResearchSupportReport)
                or review.source_prompt_version != version
                or review.resource_ref.model_copy(update={"revision": current.resource_ref.revision})
                != current.resource_ref):
            continue
        prefix = inputs[:index]
        original = next((item for item in reversed(prefix) if isinstance(item, ResearchClaims)
                         and item.resource_ref == review.resource_ref), None)
        if original is None:
            raise ValueError("source judgment has no original claim revision")
        previous = next((item for item in original.claims if item.claim_id == claim.claim_id), None)
        if previous == claim and materialize_cited_draft((previous,), prefix)[0] == unit:
            return review
    return None


def applicable_research_review(
    current: ResearchClaims | None, inputs: Sequence[InteractionInput], *, reuse_start_index: int,
) -> ResearchReview | None:
    """Project the current repair feedback, including a retained rejection."""
    if current is None:
        return None
    latest = next((item for item in reversed(inputs) if isinstance(item, ResearchReview)), None)
    if (latest is not None and latest.resource_ref == current.resource_ref
            and isinstance(latest.report, ResearchCoverageReport)):
        return latest
    selected = None
    for claim, unit in zip(current.claims, materialize_cited_draft(current.claims, inputs), strict=True):
        review = _applicable_source_review(current, claim, unit, inputs, reuse_start_index)
        if review is not None:
            selected = review
            assert isinstance(review.report, ResearchSupportReport)
            if review.report.findings:
                return review
    return selected


class ResearchSourceFeedback(_Strict):
    review: ResearchReview
    execution_evidence: tuple[CitedEvidence, ...]


def research_review_context(
    review: ResearchReview | None, inputs: Sequence[InteractionInput],
) -> ResearchSourceFeedback | None:
    """Resolve verifier-local evidence IDs from the original bound input."""
    if (review is None or not isinstance(review.report, ResearchSupportReport)
            or not review.report.findings):
        return None
    index = next(index for index, item in enumerate(inputs) if item is review)
    prefix = inputs[:index]
    original = next(item for item in reversed(prefix) if isinstance(item, ResearchClaims)
                    and item.resource_ref == review.resource_ref)
    claim = next(item for item in original.claims if item.claim_id == review.claim_id)
    relevant_ids = {identity for finding in review.report.findings for identity in finding.evidence_ids}
    return ResearchSourceFeedback(
        review=review, execution_evidence=tuple(
            evidence for evidence in materialize_cited_draft((claim,), prefix)[0].execution_evidence
            if evidence.id in relevant_ids
        ),
    )


def research_coverage_request(
    current: ResearchClaims, inputs: Sequence[InteractionInput],
    messages: Sequence[ConversationMessage], criteria: ReviewCriteria,
) -> StructuredModelRequest:
    """Give coverage its own view of returned sources, independent of draft citations."""
    visible = materialize_citation_context(materialize_interaction_inputs(inputs))
    seen: set[str] = set()
    sources = []
    for item in visible:
        if not isinstance(item.observation, ActionObservation):
            continue
        lines = []
        for citation in item.citations:
            if citation.evidence_id not in seen:
                seen.add(citation.evidence_id)
                lines.append(citation)
        if lines or item.observation.payload.get("retrieval"):
            sources.append(item.model_copy(update={"citations": tuple(lines)}))
    return research_request("conversation.research.coverage", ResearchCoverageReport, {
        "conversation": [message.model_dump(mode="json") for message in messages],
        "requirements": [item.model_dump(mode="json") for item in research_goal_requirements(criteria)],
        "claims": current.model_dump(mode="json"),
        "source_material": [item.model_dump(mode="json") for item in sources],
        "source_reading_state": [state.model_dump(mode="json") for state in materialize_source_reading_state(inputs)],
    })


def validate_research_coverage(
    report: ResearchCoverageReport, criteria: ReviewCriteria,
    current: ResearchClaims, inputs: Sequence[InteractionInput],
) -> None:
    expected = {item.criterion_id for item in research_goal_requirements(criteria)}
    actual = [item.criterion_id for item in report.requirements]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError("research coverage must account for every frozen criterion exactly once")
    valid_claim_ids = {claim.claim_id for claim in current.claims}
    if any(not set(item.claim_ids).issubset(valid_claim_ids) for item in report.requirements):
        raise ValueError("research coverage must reference only current claim identities")
    selected_citation_ids(tuple(reference for item in report.requirements for reference in item.references), inputs)


def verification_steps(
    current: ResearchClaims, inputs: Sequence[InteractionInput], messages: Sequence[ConversationMessage],
    criteria: ReviewCriteria,
    *, reuse_start_index: int,
) -> Generator[StructuredModelRequest | ResearchReview, BaseModel | None, None]:
    """Bind every current claim; only changed or unchecked inputs call the model."""
    assert 0 <= reuse_start_index <= len(inputs)
    units = materialize_cited_draft(current.claims, inputs)
    for claim, unit in zip(current.claims, units, strict=True):
        previous = _applicable_source_review(current, claim, unit, inputs, reuse_start_index)
        if previous is not None:
            assert isinstance(previous.report, ResearchSupportReport)
            if previous.report.findings:
                return
            continue
        fragments = editable_claim_fragments(claim)
        report = yield research_request("conversation.research.support", ResearchSupportReport, {
            **unit.model_dump(mode="json"),
            "fragments": [fragment.model_dump(mode="json") for fragment in fragments],
        })
        assert isinstance(report, ResearchSupportReport)
        valid_ids = {evidence.id for evidence in unit.execution_evidence}
        positions = {fragment.fragment_id: index for index, fragment in enumerate(fragments)}
        for finding in report.findings:
            if len(set(finding.evidence_ids)) != len(finding.evidence_ids) or not set(finding.evidence_ids).issubset(valid_ids):
                raise ValueError("research support finding must reference only submitted evidence")
            if (finding.start_fragment_id not in positions or finding.end_fragment_id not in positions
                    or positions[finding.start_fragment_id] > positions[finding.end_fragment_id]):
                raise ValueError("research support finding must bind an ordered current claim fragment range")
        yield ResearchReview(resource_ref=current.resource_ref, claim_id=claim.claim_id,
                             report=report, source_prompt_version=get_prompt("conversation.research.support").version)
        if report.findings:
            return
    report = yield research_coverage_request(current, inputs, messages, criteria)
    assert isinstance(report, ResearchCoverageReport)
    validate_research_coverage(report, criteria, current, inputs)
    yield ResearchReview(resource_ref=current.resource_ref, report=report)
