"""Attach simple source numbers to visible evidence and resolve only those numbers."""
from collections.abc import Iterable
from pydantic import BaseModel, ConfigDict
from personal_agent.application.capture.web_source import WebSearchArgs, WebSearchOutput
from personal_agent.capabilities.contracts.verification import CitationSource, CitedDraftUnit, CitedEvidence, ConversationAnswerSegment
from .context_materialization import ARTIFACT_OUTPUT_CAPABILITIES, select_visible_successful_observations
from .models import ActionObservation, InteractionInput
from .artifact_search import SearchActionOutputArguments, SourceSearchResult
from .source_reading import SourceReadWindow, source_metadata_by_resource


class CitationBindingError(ValueError):
    reason_code = "citation_source_unavailable"


class AvailableCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    line: int | None
    text: str
    source: CitationSource | None = None


class CitableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation: InteractionInput
    evidence_id: str | None = None
    executed_query: WebSearchArgs | SearchActionOutputArguments | None = None


def _separate_executed_query(item: InteractionInput) -> tuple[InteractionInput, WebSearchArgs | SearchActionOutputArguments | None]:
    """Only source results enter citation binding; queries remain decision data."""
    if not isinstance(item, ActionObservation) or item.status != "succeeded":
        return item, None
    if item.capability_id == "web_search":
        output = WebSearchOutput.model_validate(item.payload["data"])
        query = WebSearchArgs(query=output.query, limit=output.limit)
        payload = {**item.payload, "data": output.model_dump(mode="json", exclude={"query", "limit"})}
    elif item.capability_id == "search_action_output":
        output = SourceSearchResult.model_validate({key: value for key, value in item.payload.items() if key != "ok"})
        query = SearchActionOutputArguments(resource_ref=output.resource_ref, keyword=output.keyword,
                                           regex=output.regex, result_offset=output.result_offset)
        payload = {key: value for key, value in item.payload.items() if key not in {"keyword", "regex", "result_offset"}}
    else:
        return item, None
    return item.model_copy(update={"payload": payload}), query


def _catalog(inputs: Iterable[InteractionInput]) -> dict[str, tuple[AvailableCitation, ...]]:
    visible = select_visible_successful_observations(inputs, excluded_capability_ids=frozenset({"verify_interaction_draft"}))
    sources = source_metadata_by_resource(visible)
    catalog: dict[str, tuple[AvailableCitation, ...]] = {}
    number = 0
    for observation in visible:
        observation, _ = _separate_executed_query(observation)
        if observation.action_id in catalog:
            raise ValueError("visible evidence requires unique execution action ids")
        number += 1
        locations = [AvailableCitation(evidence_id=f"e{number}", line=None, text=observation.model_dump_json())]
        if observation.capability_id in ARTIFACT_OUTPUT_CAPABILITIES and not observation.payload.get("retrieval"):
            window = SourceReadWindow.model_validate(observation.payload)
            if len({line.line for line in window.lines}) != len(window.lines):
                raise ValueError("one read window must return each line at most once")
            for line in window.lines:
                number += 1
                metadata = sources.get(window.resource_ref)
                locations.append(AvailableCitation(
                    evidence_id=f"e{number}", line=line.line, text=line.text,
                    source=CitationSource(
                        resource_ref=window.resource_ref,
                        source_url=(metadata[0] or None) if metadata is not None else None,
                        line=line.line, start_column=line.start_column,
                    ),
                ))
        catalog[observation.action_id] = tuple(locations)
    return catalog


def materialize_citation_context(inputs: Iterable[InteractionInput]) -> tuple[CitableInput, ...]:
    inputs = tuple(inputs)
    catalog = _catalog(inputs)
    result = []
    for item in inputs:
        locations = catalog.get(item.action_id, ()) if isinstance(item, ActionObservation) else ()
        item, query = _separate_executed_query(item)
        if len(locations) > 1:
            identifiers = {location.line: location.evidence_id for location in locations[1:]}
            payload = {**item.payload, "lines": [
                {**line, "evidence_id": identifiers[line["line"]]} for line in item.payload["lines"]
            ]}
            item = item.model_copy(update={"payload": payload})
        result.append(CitableInput(observation=item, evidence_id=locations[0].evidence_id if locations else None,
                                  executed_query=query))
    return tuple(result)


def materialize_cited_draft(segments: tuple[ConversationAnswerSegment, ...], inputs: Iterable[InteractionInput]) -> tuple[CitedDraftUnit, ...]:
    catalog = {location.evidence_id: location for locations in _catalog(inputs).values() for location in locations}
    units = []
    for segment in segments:
        restored = []
        for ref in segment.references:
            if ref.evidence_id not in catalog:
                raise CitationBindingError(f"引用 {ref.evidence_id} 不在本次实际可见证据中。请原样复制正文旁的 evidence_id；需要其他内容时继续读取。")
            location = catalog[ref.evidence_id]
            restored.append(CitedEvidence(id=f"e{len(restored)+1:03d}", text=location.text, source=location.source))
        units.append(CitedDraftUnit(draft=segment.text, execution_evidence=tuple(restored)))
    assert "".join(unit.draft for unit in units) == "".join(segment.text for segment in segments)
    return tuple(units)
