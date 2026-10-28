"""Claim admission and version-bound research checks in the Conversation loop."""

import json
from dataclasses import replace
from collections.abc import Generator, Sequence
from typing import Annotated, Literal, cast

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, create_model

from personal_agent.capabilities.contracts.model import (
    StructuredModelRequest,
    sealed_context_projection_ref,
)
from personal_agent.capabilities.contracts.research import (
    ResearchAnswerTarget,
    ResearchClaim,
    ResearchClaimContent,
    ResearchClaims,
    ResearchClaimSpan,
    ResearchRequirementTarget,
    ResearchSupportFinding,
    ResearchReview,
    ResearchSupportReport,
)
from personal_agent.capabilities.contracts.verification import (
    CitedDraftUnit,
    CitedEvidence,
    ConversationAnswerSegment,
    ConversationEvidenceReference,
    SourceReadingState,
)
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.kernel.prompt_registry import PromptCatalog
from personal_agent.kernel.prompts import DEFAULT_PROMPTS

from .citations import (
    CitableInput,
    materialize_citation_context,
    materialize_cited_draft,
    materialize_reference_sources,
    selected_citation_ids,
)
from .context_materialization import materialize_interaction_inputs
from .models import (
    ActionObservation,
    ConversationMessage,
    InteractionInput,
    ReviewCriteria,
    ResearchEvidenceSelection,
)
from .source_reading import materialize_source_reading_state


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResearchGoalRequirement(_Strict):
    """Read-only identity projection of the frozen interaction requirements."""

    criterion_id: str = Field(pattern=r"^r[1-9][0-9]*$")
    criterion: str


def research_goal_requirements(
    criteria: ReviewCriteria,
) -> tuple[ResearchGoalRequirement, ...]:
    return tuple(
        ResearchGoalRequirement(criterion_id=f"r{index}", criterion=criterion)
        for index, criterion in enumerate(criteria.criteria, start=1)
    )



def validate_research_selection(
    selection: ResearchEvidenceSelection,
    criteria: ReviewCriteria,
    current: ResearchClaims | None,
) -> None:
    """Own exact goal accounting; semantic sufficiency remains model-owned."""
    expected = {item.criterion_id for item in research_goal_requirements(criteria)}
    actual = [need.criterion_id for need in selection.needs]
    if len(set(actual)) != len(actual) or set(actual) != expected:
        raise ValueError(
            "research selection must account for every frozen criterion exactly once; "
            f"expected={sorted(expected)}, actual={actual}"
        )
    claim_ids = {claim.claim_id for claim in current.claims} if current else set()
    if any(not set(need.claim_ids).issubset(claim_ids) for need in selection.needs):
        raise ValueError("research selection must identify only current claims")


class CreateClaims(_Strict):
    kind: Literal["create_claims"]
    claims: tuple[ResearchClaimContent, ...] = Field(min_length=1)
    final_answer: tuple[ConversationAnswerSegment | ResearchAnswerTarget, ...] | None = Field(
        default=None, min_length=1,
        description="可选的完整最终回答顺序；新段提交 text/references，未改段以当前 answer_segment_id 引用。",
    )


class _Edit(_Strict):
    base_ref: ResourceRef
    final_answer: tuple[ConversationAnswerSegment | ResearchAnswerTarget, ...] | None = Field(
        default=None, min_length=1,
        description="可选的完整最终回答顺序；新段提交 text/references，未改段以当前 base_ref 的 answer_segment_id 引用。",
    )


class ReviseClaimFragment(_Edit):
    kind: Literal["revise_claim_fragment"]
    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    start_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    end_fragment_id: str = Field(pattern=r"^c[1-9][0-9]*\.f[1-9][0-9]*$")
    replacement: str
    additional_references: tuple[ConversationEvidenceReference, ...] = Field(
        default=(),
        description="与本次正文修订一同提交的新增引用；已有引用由 Runtime 保留，新增坐标须本轮选中。",
    )


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


class EditableClaimFragment(_Strict):
    fragment_id: str
    text: str
    start: int = Field(exclude=True)
    end: int = Field(exclude=True)


class EditableClaim(_Strict):
    claim_id: str
    fragments: tuple[EditableClaimFragment, ...]
    references: tuple[ConversationEvidenceReference, ...]


class EditableResearchAnswerSegment(ConversationAnswerSegment):
    """Read-only address of an existing paragraph in this research revision."""

    answer_segment_id: str = Field(pattern=r"^a[1-9][0-9]*$")


class ResearchSourceClaim(CitedDraftUnit):
    """The complete claim and its own bound evidence, with lossless addresses."""

    claim_id: str = Field(pattern=r"^c[1-9][0-9]*$")
    fragments: tuple[EditableClaimFragment, ...]


class ResearchAnswerUnit(CitedDraftUnit):
    answer_segment_id: str = Field(pattern=r"^a[1-9][0-9]*$")


class MissingResearchFinalAnswer(ValueError):
    reason_code = "final_answer_missing"


class ResearchSourceInput(_Strict):
    """One complete research revision, frozen goals and actual returned evidence."""

    research_ref: ResourceRef
    conversation: tuple[ConversationMessage, ...]
    requirements: tuple[ResearchGoalRequirement, ...]
    claims: tuple[ResearchSourceClaim, ...] = Field(min_length=1)
    final_answer: tuple[ResearchAnswerUnit, ...] = Field(min_length=1)
    returned_evidence: tuple[CitableInput, ...]
    source_reading_state: tuple[SourceReadingState, ...]


class EditableResearchClaims(_Strict):
    kind: Literal["research_claims"] = "research_claims"
    resource_ref: ResourceRef
    claims: tuple[EditableClaim, ...]
    final_answer: tuple[EditableResearchAnswerSegment, ...] | None


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
    fragments = tuple(
        EditableClaimFragment(
            fragment_id=f"{claim.claim_id}.f{number}",
            text=text[start:end],
            start=start,
            end=end,
        )
        for number, (start, end) in enumerate(ranges, 1)
    )
    assert fragments and "".join(fragment.text for fragment in fragments) == text
    return fragments


def editable_research_claims(current: ResearchClaims) -> EditableResearchClaims:
    return EditableResearchClaims(
        resource_ref=current.resource_ref,
        claims=tuple(
            EditableClaim(
                claim_id=claim.claim_id,
                fragments=editable_claim_fragments(claim),
                references=claim.references,
            )
            for claim in current.claims
        ),
        final_answer=(
            tuple(
                EditableResearchAnswerSegment(
                    **segment.model_dump(), answer_segment_id=f"a{index}"
                )
                for index, segment in enumerate(current.final_answer, 1)
            )
            if current.final_answer is not None else None
        ),
    )


class ResearchDocumentBounds(_Strict):
    document_id: str
    full_line_ranges: tuple[str, ...]
    partial_line_coordinates: tuple[str, ...]


def research_operation_schema(
    operation: type[BaseModel],
    current: ResearchClaims | None,
    inputs: Sequence[CitableInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> dict:
    """Project the current argument scope into the Provider's JSON Schema.

    Admission remains the sole owner of binding. The scoped type inherits the
    canonical submission contract and adds no stored or model-authored facts.
    """
    coordinates = {
        citation.evidence_id for item in inputs for citation in item.citations
    }
    documents = sorted(
        {coordinate.split(":")[0] for coordinate in coordinates},
        key=lambda value: int(value[1:]),
    )
    bounds = []
    for document in documents:
        lines = sorted(
            int(value.split(":")[1])
            for value in coordinates
            if value.split(":")[0] == document and value.count(":") == 1
        )
        spans: list[tuple[int, int]] = []
        for line in lines:
            if spans and spans[-1][1] + 1 == line:
                spans[-1] = (spans[-1][0], line)
            else:
                spans.append((line, line))
        bounds.append(
            ResearchDocumentBounds(
                document_id=document,
                full_line_ranges=tuple(
                    f"{document}:{start}"
                    if start == end
                    else f"{document}:{start}-{end}"
                    for start, end in spans
                ),
                partial_line_coordinates=tuple(
                    sorted(
                        value
                        for value in coordinates
                        if value.split(":")[0] == document and value.count(":") == 2
                    )
                ),
            )
        )
    claim_ids = [claim.claim_id for claim in current.claims] if current else []
    fragment_ids = (
        [
            fragment.fragment_id
            for claim in current.claims
            for fragment in editable_claim_fragments(claim)
        ]
        if current
        else []
    )
    schema = operation.model_json_schema()
    definitions = schema.get("$defs", {})
    definitions[operation.__name__] = schema
    for name in (
        "ReviseClaimFragment",
        "ReplaceClaimReferences",
        "DeleteClaim",
    ):
        if name in definitions:
            definitions[name]["properties"]["claim_id"]["enum"] = claim_ids
    if "ReviseClaimFragment" in definitions:
        for field in ("start_fragment_id", "end_fragment_id"):
            definitions["ReviseClaimFragment"]["properties"][field]["enum"] = (
                fragment_ids
            )
    reference = definitions.get("ConversationEvidenceReference", {}).get("properties", {}).get("evidence_id", {})
    docs = "|".join(documents)
    reference["pattern"] = (
        rf"^(?:{docs}):[1-9][0-9]*(?:-[1-9][0-9]*|:[1-9][0-9]*-[1-9][0-9]*)?$"
        if docs
        else r"^(?!)$"
    )
    reference["description"] = prompts.render(
        "conversation.research.reference_scope", bounds=json.dumps(
            [bound.model_dump(mode="json") for bound in bounds],
            ensure_ascii=False,
        ),
    )
    if "ResearchAnswerTarget" in definitions:
        definitions["ResearchAnswerTarget"]["properties"]["answer_segment_id"]["enum"] = (
            [f"a{index}" for index in range(1, len(current.final_answer or ()) + 1)]
            if current is not None else []
        )
    definitions.pop(operation.__name__, None)
    return schema


def current_claims(inputs: Sequence[InteractionInput]) -> ResearchClaims | None:
    return next(
        (item for item in reversed(inputs) if isinstance(item, ResearchClaims)), None
    )


def in_research_mode(
    inputs: Sequence[InteractionInput],
    *,
    requires_review: bool,
    experiment_run: bool = False,
) -> bool:
    return (
        not experiment_run
        and (
            current_claims(inputs) is not None
            or (
                requires_review
                and any(
                    isinstance(item, ActionObservation)
                    and item.status == "succeeded"
                    and item.capability_id in {"web_search", "web_read"}
                    for item in inputs
                )
            )
        )
    )


def accepted_research(
    inputs: Sequence[InteractionInput], *, reuse_start_index: int = 0,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> ResearchClaims | None:
    """Completion reads only the exact current revision with an applicable pass."""
    current = current_claims(inputs)
    if current is None or not current.final_answer or not "".join(
        segment.text for segment in current.final_answer
    ).strip():
        return None
    review = _applicable_source_review(current, inputs, reuse_start_index, prompts)
    if review is None or review.report.findings:
        return None
    materialize_cited_draft(current.final_answer, inputs, prompts=prompts)
    return current


def admit_claim_change(
    action: CreateClaims
    | ReviseClaimFragment
    | ReplaceClaimReferences
    | AddClaims
    | DeleteClaim
    | RecheckClaims,
    inputs: Sequence[InteractionInput],
    initial_ref: ResourceRef,
    selected_ids: frozenset[str],
    *,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> ResearchClaims:
    """Only this owner assigns identities and changes exact current claim text."""
    current = current_claims(inputs)
    next_id = 1 + max(
        (
            int(claim.claim_id[1:])
            for item in inputs
            if isinstance(item, ResearchClaims)
            for claim in item.claims
        ),
        default=0,
    )

    def identify(parts: tuple[ResearchClaimContent, ...]) -> tuple[ResearchClaim, ...]:
        return tuple(
            ResearchClaim(**part.model_dump(), claim_id=f"c{next_id + index}")
            for index, part in enumerate(parts)
        )

    def require_selected(
        parts: tuple[ConversationAnswerSegment, ...],
        inherited_ids: frozenset[str] = frozenset(),
    ) -> None:
        for part in parts:
            unselected = (
                selected_citation_ids(part.references, inputs, prompts=prompts)
                - inherited_ids
                - selected_ids
            )
            if unselected:
                raise ValueError(
                    prompts.render(
                        "conversation.research.unselected_references",
                        unselected=", ".join(sorted(unselected)),
                    )
                )

    if isinstance(action, CreateClaims):
        if current is not None:
            raise ValueError(prompts.render("conversation.research.collection_exists"))
        require_selected(action.claims)
        claims = identify(action.claims)
        reference = initial_ref
    else:
        if current is None or action.base_ref != current.resource_ref:
            raise ValueError(
                prompts.render("conversation.research.base_ref_mismatch")
            )
        reference = current.resource_ref.model_copy(
            update={"revision": current.resource_ref.revision + 1}
        )
        claims = current.claims
        if isinstance(action, AddClaims):
            require_selected(action.claims)
            claims += identify(action.claims)
        elif not isinstance(action, RecheckClaims):
            index = next(
                (
                    i
                    for i, claim in enumerate(claims)
                    if claim.claim_id == action.claim_id
                ),
                None,
            )
            if index is None:
                raise ValueError(prompts.render("conversation.research.claim_unknown"))
            if isinstance(action, DeleteClaim):
                if len(claims) == 1:
                    raise ValueError(
                        prompts.render("conversation.research.last_claim")
                    )
                claims = claims[:index] + claims[index + 1 :]
            elif isinstance(action, ReviseClaimFragment):
                claim = claims[index]
                fragments = {
                    fragment.fragment_id: fragment
                    for fragment in editable_claim_fragments(claim)
                }
                start = fragments.get(action.start_fragment_id)
                end = fragments.get(action.end_fragment_id)
                if start is None or end is None or start.start > end.start:
                    raise ValueError(
                        prompts.render("conversation.research.fragment_range_invalid")
                    )
                updated = (
                    claim.text[: start.start]
                    + action.replacement
                    + claim.text[end.end :]
                )
                if not updated.strip():
                    raise ValueError(prompts.render("conversation.research.claim_empty"))
                references = tuple(
                    dict.fromkeys((*claim.references, *action.additional_references))
                )
                require_selected(
                    (claim.model_copy(update={"references": references}),),
                    selected_citation_ids(claim.references, inputs, prompts=prompts),
                )
                replacements = (
                    ResearchClaim(
                        claim_id=claim.claim_id, text=updated, references=references
                    ),
                )
                claims = claims[:index] + replacements + claims[index + 1 :]
            elif isinstance(action, ReplaceClaimReferences):
                claim = claims[index]
                require_selected(
                    (claim.model_copy(update={"references": action.references}),),
                    selected_citation_ids(claim.references, inputs, prompts=prompts),
                )
                replacements = (
                    ResearchClaim(
                        claim_id=claim.claim_id,
                        text=claim.text,
                        references=action.references,
                    ),
                )
                claims = claims[:index] + replacements + claims[index + 1 :]
            else:
                raise ValueError("unsupported claim change")
    answer = None
    if action.final_answer is not None:
        previous = {
            f"a{index}": segment
            for index, segment in enumerate(current.final_answer or (), 1)
        } if current is not None else {}
        restored = []
        for segment in action.final_answer:
            if isinstance(segment, ResearchAnswerTarget):
                existing = previous.get(segment.answer_segment_id)
                if existing is None:
                    raise ValueError(prompts.render("conversation.research.answer_segment_unknown"))
                restored.append(existing)
            else:
                restored.append(segment)
        answer = tuple(restored)
    elif isinstance(action, RecheckClaims) and current is not None:
        answer = current.final_answer
    result = ResearchClaims(resource_ref=reference, claims=claims, final_answer=answer)
    # Coordinates must bind before any journal mutation or semantic call.
    materialize_cited_draft(result.claims, inputs, prompts=prompts)
    if answer is not None:
        bound_claim_ids = selected_citation_ids(
            tuple(reference for claim in result.claims for reference in claim.references), inputs,
            prompts=prompts,
        )
        bound_answer_ids = selected_citation_ids(
            tuple(reference for segment in answer for reference in segment.references), inputs,
            prompts=prompts,
        )
        if not bound_answer_ids.issubset(bound_claim_ids):
            raise ValueError(prompts.render("conversation.research.final_references_unbound"))
        materialize_cited_draft(answer, inputs, prompts=prompts)
    return result


def research_request(
    name: str, output_type: type[BaseModel], payload: dict,
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> StructuredModelRequest:
    prompt = prompts.get(name)
    messages = [
        {"role": "system", "content": prompt.template},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
    return StructuredModelRequest(
        operation=name.replace(".", "_"),
        version=prompt.version,
        messages=messages,
        output_type=output_type,
        output_transport="native_tool",
        temperature=0,
        max_tokens=131_072,
        context_projection_ref=sealed_context_projection_ref(
            purpose=name, messages=messages
        ),
        metadata={"component": "conversation_research"},
    )


def _applicable_source_review(
    current: ResearchClaims,
    inputs: Sequence[InteractionInput],
    reuse_start_index: int,
    prompts: PromptCatalog,
) -> ResearchReview | None:
    """A whole-revision judgment is valid only for the same complete input.

    The journal owns this run's immutable messages and review criteria. Its
    resource identity binds that frozen goal; evidence is rebuilt from the
    exact original prefix rather than copied into an approval mirror.
    """
    version = research_source_prompt_version(prompts=prompts)
    for index in range(len(inputs) - 1, reuse_start_index - 1, -1):
        review = inputs[index]
        if (
            not isinstance(review, ResearchReview)
            or review.resource_ref != current.resource_ref
            or review.source_prompt_version != version
        ):
            continue
        prefix = inputs[:index]
        original = current_claims(prefix)
        if original is None:
            raise ValueError("research judgment has no original revision")
        if (
            original == current
            and materialize_reference_sources(original.claims, prefix, prompts=prompts)
            == materialize_reference_sources(current.claims, inputs, prompts=prompts)
            and _returned_research_sources(prefix) == _returned_research_sources(inputs)
            and materialize_source_reading_state(prefix)
            == materialize_source_reading_state(inputs)
        ):
            return review
    return None


def applicable_research_review(
    current: ResearchClaims | None,
    inputs: Sequence[InteractionInput],
    *,
    reuse_start_index: int,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> ResearchReview | None:
    if current is None:
        return None
    return _applicable_source_review(current, inputs, reuse_start_index, prompts)


class ResearchSourceFeedback(_Strict):
    review: ResearchReview
    execution_evidence: tuple[CitedEvidence, ...]


def _claim_evidence(
    claim: ConversationAnswerSegment, inputs: Sequence[InteractionInput],
    *, prompts: PromptCatalog,
) -> tuple[CitedEvidence, ...]:
    """Use existing document coordinates, avoiding per-claim eNNN collisions."""
    return tuple(
        CitedEvidence(id=location.evidence_id, text=location.text, source=location.source)
        for location in materialize_reference_sources((claim,), inputs, prompts=prompts)
    )


def research_review_context(
    review: ResearchReview | None,
    inputs: Sequence[InteractionInput],
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> ResearchSourceFeedback | None:
    if review is None or not review.report.findings:
        return None
    index = next(index for index, item in enumerate(inputs) if item is review)
    prefix = inputs[:index]
    original = current_claims(prefix)
    if original is None or original.resource_ref != review.resource_ref:
        raise ValueError("research feedback must bind its original revision")
    relevant_ids = {
        identity for finding in review.report.findings for identity in finding.evidence_ids
    }
    evidence_by_id = {
        evidence.id: evidence
        for evidence in (
            *_returned_research_evidence(prefix),
            *(evidence for claim in original.claims for evidence in _claim_evidence(claim, prefix, prompts=prompts)),
        )
        if evidence.id in relevant_ids
    }
    return ResearchSourceFeedback(
        review=review, execution_evidence=tuple(evidence_by_id.values()),
    )


def _returned_research_sources(
    inputs: Sequence[InteractionInput],
) -> tuple[CitableInput, ...]:
    """One read-only projection of visible, actually returned source coordinates."""
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
        sources.append(item.model_copy(update={"citations": tuple(lines)}))
    return tuple(sources)


def _returned_research_evidence(
    inputs: Sequence[InteractionInput],
) -> tuple[CitedEvidence, ...]:
    return tuple(
        CitedEvidence(id=location.evidence_id, text=location.text, source=location.source)
        for item in _returned_research_sources(inputs)
        for location in item.citations
    )


def research_support_input(
    current: ResearchClaims,
    inputs: Sequence[InteractionInput],
    messages: Sequence[ConversationMessage],
    criteria: ReviewCriteria,
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> ResearchSourceInput:
    if not current.final_answer or not "".join(segment.text for segment in current.final_answer).strip():
        raise MissingResearchFinalAnswer(prompts.render("conversation.research.final_answer_missing"))
    claim_ids = selected_citation_ids(tuple(ref for claim in current.claims for ref in claim.references), inputs, prompts=prompts)
    answer_ids = selected_citation_ids(tuple(ref for segment in current.final_answer for ref in segment.references), inputs, prompts=prompts)
    if not answer_ids.issubset(claim_ids):
        raise ValueError(prompts.render("conversation.research.final_bound_coordinates"))
    return ResearchSourceInput(
        research_ref=current.resource_ref,
        conversation=tuple(messages),
        requirements=research_goal_requirements(criteria),
        claims=tuple(
            ResearchSourceClaim(
                claim_id=claim.claim_id, draft=claim.text,
                fragments=editable_claim_fragments(claim),
                execution_evidence=_claim_evidence(claim, inputs, prompts=prompts),
            )
            for claim in current.claims
        ),
        final_answer=tuple(
            ResearchAnswerUnit(
                answer_segment_id=f"a{index}", draft=segment.text,
                execution_evidence=_claim_evidence(segment, inputs, prompts=prompts),
            )
            for index, segment in enumerate(current.final_answer, 1)
        ),
        returned_evidence=_returned_research_sources(inputs),
        source_reading_state=materialize_source_reading_state(inputs),
    )


def research_source_prompt_version(*, prompts: PromptCatalog = DEFAULT_PROMPTS) -> str:
    return prompts.get("conversation.research.support").version


def validate_research_support(
    report: ResearchSupportReport, source_input: ResearchSourceInput,
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> None:
    """Own finding references; semantic correctness remains with the model."""
    returned_ids = {
        line.evidence_id for item in source_input.returned_evidence for line in item.citations
    }
    requirement_ids = {item.criterion_id for item in source_input.requirements}
    fragments = {
        fragment.fragment_id: (claim, index)
        for claim in source_input.claims
        for index, fragment in enumerate(claim.fragments)
    }
    answer_units = {unit.answer_segment_id: unit for unit in source_input.final_answer}
    for finding in report.findings:
        target = finding.target
        if isinstance(target, ResearchRequirementTarget):
            if target.criterion_id not in requirement_ids:
                raise ValueError(prompts.render("conversation.research.support_requirement_unknown"))
            allowed_ids = returned_ids
        elif isinstance(target, ResearchAnswerTarget):
            unit = answer_units.get(target.answer_segment_id)
            if unit is None:
                raise ValueError(prompts.render("conversation.research.support_answer_unknown"))
            bound_ids = {evidence.id for evidence in unit.execution_evidence}
            allowed_ids = bound_ids if finding.category == "citation_not_supported" else bound_ids | returned_ids
        else:
            start = fragments.get(target.start_fragment_id)
            end = fragments.get(target.end_fragment_id)
            if start is None or end is None or start[0].claim_id != end[0].claim_id or start[1] > end[1]:
                raise ValueError(prompts.render("conversation.research.support_fragment_invalid"))
            bound_ids = {evidence.id for evidence in start[0].execution_evidence}
            allowed_ids = bound_ids if finding.category == "citation_not_supported" else bound_ids | returned_ids
        if len(set(finding.evidence_ids)) != len(finding.evidence_ids) or not set(finding.evidence_ids).issubset(allowed_ids):
            raise ValueError(prompts.render("conversation.research.support_evidence_invalid"))


def research_support_output_type(
    source_input: ResearchSourceInput, *, prompts: PromptCatalog = DEFAULT_PROMPTS
) -> type[ResearchSupportReport]:
    """Publish the same contract with current IDs and read-boundary validation."""
    fragment_ids = tuple(fragment.fragment_id for claim in source_input.claims for fragment in claim.fragments)
    requirement_ids = tuple(item.criterion_id for item in source_input.requirements)
    span = create_model(
        "CurrentResearchClaimSpan", __base__=ResearchClaimSpan,
        start_fragment_id=(Literal[fragment_ids], ...),
        end_fragment_id=(Literal[fragment_ids], ...),
    )
    target = create_model(
        "CurrentResearchRequirementTarget", __base__=ResearchRequirementTarget,
        criterion_id=(Literal[requirement_ids], ...) if requirement_ids else (
            str, Field(pattern=r"^(?!)$"),
        ),
    )
    answer_target = create_model(
        "CurrentResearchAnswerTarget", __base__=ResearchAnswerTarget,
        answer_segment_id=(Literal[tuple(unit.answer_segment_id for unit in source_input.final_answer)], ...),
    )
    finding = create_model(
        "CurrentResearchSupportFinding", __base__=ResearchSupportFinding,
        target=(span | target | answer_target, ...),
    )

    def check_finding(value: ResearchSupportFinding) -> ResearchSupportFinding:
        validate_research_support(
            ResearchSupportReport(findings=(value,)), source_input, prompts=prompts
        )
        return value

    bound_finding = Annotated[finding, AfterValidator(check_finding)]
    report = create_model(
        "CurrentResearchSupportReport", __base__=ResearchSupportReport,
        findings=(tuple[bound_finding, ...], ...),
    )
    return cast(type[ResearchSupportReport], report)


def research_support_request(
    source_input: ResearchSourceInput, *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> StructuredModelRequest:
    return replace(
        research_request(
            "conversation.research.support",
            research_support_output_type(source_input, prompts=prompts),
            source_input.model_dump(mode="json"),
            prompts=prompts,
        ),
        max_tokens=131_072,
        max_output_repairs=2,
    )


def research_source_steps(
    source_input: ResearchSourceInput,
    *, prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> Generator[StructuredModelRequest, BaseModel | None, ResearchSupportReport]:
    report = yield research_support_request(source_input, prompts=prompts)
    assert isinstance(report, ResearchSupportReport)
    report = ResearchSupportReport.model_validate(report.model_dump(mode="json"))
    validate_research_support(report, source_input, prompts=prompts)
    return report


def verification_steps(
    current: ResearchClaims,
    inputs: Sequence[InteractionInput],
    messages: Sequence[ConversationMessage],
    criteria: ReviewCriteria,
    *,
    reuse_start_index: int,
    prompts: PromptCatalog = DEFAULT_PROMPTS,
) -> Generator[StructuredModelRequest | ResearchReview, BaseModel | None, None]:
    """One judgment owns both support and goal coverage of this revision."""
    assert 0 <= reuse_start_index <= len(inputs)
    if _applicable_source_review(current, inputs, reuse_start_index, prompts) is not None:
        return
    report = yield from research_source_steps(
        research_support_input(current, inputs, messages, criteria, prompts=prompts),
        prompts=prompts,
    )
    yield ResearchReview(
        resource_ref=current.resource_ref, report=report,
        source_prompt_version=research_source_prompt_version(prompts=prompts),
    )
