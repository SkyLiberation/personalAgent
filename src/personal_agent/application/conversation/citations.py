"""Project and bind one citation syntax: document snapshot and returned line."""
from collections.abc import Iterable
from hashlib import sha256
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture.web_source import WEB_SOURCE_FORMAT, WebReadOutput, WebSearchArgs, WebSearchOutput
from personal_agent.capabilities.contracts.verification import CitationSource, CitedDraftUnit, CitedEvidence, ConversationAnswerSegment
from personal_agent.kernel.contracts.resource import ResourceRef
from .context_materialization import ARTIFACT_OUTPUT_CAPABILITIES, select_visible_successful_observations
from .models import ActionObservation, InteractionInput
from .artifact_search import SearchActionOutputArguments, SourceSearchResult
from .source_reading import ReturnedSourceLine, SourceReadWindow, source_metadata_by_resource


class CitationBindingError(ValueError):
    reason_code = "citation_source_unavailable"


class CitationLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    evidence_id: str
    line: int = Field(ge=1)
    text: str


class AvailableCitation(CitationLine):
    source: CitationSource


class CitableInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation: InteractionInput
    citations: tuple[CitationLine, ...] = ()
    document_kind: Literal["source_text", "tool_result"] | None = None
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


def _inline_document(observation: ActionObservation) -> tuple[CitationSource, tuple[ReturnedSourceLine, ...]]:
    data = observation.payload.get("data")
    if isinstance(data, dict) and data.get("format") == WEB_SOURCE_FORMAT:
        output = WebReadOutput.model_validate(data)
        text = output.source_text
        source = CitationSource(content_digest=sha256(text.encode("utf-8")).hexdigest(),
                                source_url=output.source_url, line=1, start_column=1)
    else:
        text = json.dumps(observation.payload, ensure_ascii=False, sort_keys=True, indent=2)
        digest = sha256((observation.capability_id + "\0" + text).encode("utf-8")).hexdigest()
        source = CitationSource(content_digest=digest, source_url=None, document_kind="tool_result", line=1, start_column=1)
    lines = tuple(ReturnedSourceLine(line=number, text=line) for number, line in enumerate(text.splitlines(),1))
    return source, lines


def _catalog(inputs: Iterable[InteractionInput]) -> dict[str, tuple[AvailableCitation, ...]]:
    visible = select_visible_successful_observations(inputs, excluded_capability_ids=frozenset({"verify_interaction_draft"}))
    sources = source_metadata_by_resource(visible)
    documents: dict[ResourceRef | CitationSource, str] = {}
    positions: dict[str, AvailableCitation] = {}
    catalog: dict[str, tuple[AvailableCitation, ...]] = {}
    for observation in visible:
        observation, _ = _separate_executed_query(observation)
        assert isinstance(observation, ActionObservation)
        if observation.action_id in catalog:
            raise ValueError("visible evidence requires unique execution action ids")
        # Offloaded excerpts are not source lines and cannot acquire a citation.
        if observation.payload.get("retrieval"):
            catalog[observation.action_id] = ()
            continue
        if observation.capability_id in ARTIFACT_OUTPUT_CAPABILITIES:
            window = SourceReadWindow.model_validate(observation.payload)
            metadata = sources.get(window.resource_ref)
            url = (metadata[0] or None) if metadata is not None else None
            source = CitationSource(resource_ref=window.resource_ref, source_url=url,
                                    document_kind="source_text" if url else "tool_result", line=1, start_column=1)
            document = documents.setdefault(window.resource_ref, f"d{len(documents) + 1}")
            lines = window.lines
            if len({line.line for line in lines}) != len(lines):
                raise ValueError("one read window must return each line at most once")
            if any(line.line > window.total_lines for line in lines):
                raise ValueError("citation line exceeds source length")
        else:
            source, lines = _inline_document(observation)
            document = documents.setdefault(source, f"d{len(documents) + 1}")
        locations = []
        for line in lines:
            end_column = line.start_column + len(line.text) - 1
            if line.line_length is not None and end_column > line.line_length:
                raise ValueError("citation range exceeds source position")
            evidence_id = f"{document}:{line.line}"
            if line.start_column != 1 or (line.line_length is not None and len(line.text) != line.line_length):
                if not line.text:
                    raise ValueError("partial source citation requires nonempty returned text")
                evidence_id += f":{line.start_column}-{end_column}"
            location = AvailableCitation(evidence_id=evidence_id, line=line.line, text=line.text,
                source=source.model_copy(update={"line":line.line,"start_column":line.start_column}))
            if positions.setdefault(evidence_id, location) != location:
                raise ValueError("one source coordinate must resolve to identical evidence")
            locations.append(location)
        catalog[observation.action_id] = tuple(locations)
    return catalog


def materialize_citation_context(inputs: Iterable[InteractionInput]) -> tuple[CitableInput, ...]:
    inputs = tuple(inputs)
    catalog = _catalog(inputs)
    result = []
    for item in inputs:
        locations = catalog.get(item.action_id, ()) if isinstance(item, ActionObservation) else ()
        item, query = _separate_executed_query(item)
        if locations:
            assert isinstance(item, ActionObservation)
            if item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES:
                payload = {key:value for key,value in item.payload.items() if key != "lines"}
            elif locations[0].source.document_kind == "source_text":
                payload = {**item.payload,"data":{key:value for key,value in item.payload["data"].items() if key != "source_text"}}
            else:
                # The exact result document is in citations; do not repeat its body.
                payload = {}
            item = item.model_copy(update={"payload":payload})
        result.append(CitableInput(observation=item, citations=locations,
            document_kind=locations[0].source.document_kind if locations else None, executed_query=query))
    return tuple(result)


def _resolve_citation(evidence_id: str, catalog: dict[str, AvailableCitation]) -> tuple[AvailableCitation, ...]:
    """Expand a writer's range only into exact, already returned full lines."""
    document, position, *columns = evidence_id.split(":")
    coordinates = (evidence_id,)
    if not columns and "-" in position:
        start, end = (int(value) for value in position.split("-"))
        if end <= start or end - start + 1 > len(catalog):
            raise CitationBindingError(f"引用 {evidence_id} 不是可见的连续多行范围；结束行须大于起始行，且每行已完整返回。")
        coordinates = tuple(f"{document}:{line}" for line in range(start, end + 1))
    missing = next((coordinate for coordinate in coordinates if coordinate not in catalog), None)
    if missing is not None:
        raise CitationBindingError(f"引用 {evidence_id} 中的 {missing} 未完整返回或不存在。请选择 citations 中实际可见的行；连续范围不能跳过缺行，部分行须原样保留字符范围，需要其他内容时继续读取。")
    return tuple(catalog[coordinate] for coordinate in coordinates)


def materialize_cited_draft(segments: tuple[ConversationAnswerSegment, ...], inputs: Iterable[InteractionInput]) -> tuple[CitedDraftUnit, ...]:
    catalog = {location.evidence_id: location for locations in _catalog(inputs).values() for location in locations}
    units = []
    for segment in segments:
        restored = []
        for ref in segment.references:
            for location in _resolve_citation(ref.evidence_id, catalog):
                restored.append(CitedEvidence(id=f"e{len(restored)+1:03d}", text=location.text, source=location.source))
        units.append(CitedDraftUnit(draft=segment.text, execution_evidence=tuple(restored)))
    assert "".join(unit.draft for unit in units) == "".join(segment.text for segment in segments)
    return tuple(units)


def materialize_reference_sources(segments: tuple[ConversationAnswerSegment, ...], inputs: Iterable[InteractionInput]) -> tuple[AvailableCitation, ...]:
    """Keep document coordinates when projecting source identity for synthesis.

    CitedDraftUnit uses verifier-local eNNN identities, which must never escape
    as Conversation document references.
    """
    catalog = {location.evidence_id: location for locations in _catalog(inputs).values() for location in locations}
    return tuple(dict.fromkeys(
        location for segment in segments for ref in segment.references
        for location in _resolve_citation(ref.evidence_id, catalog)
    ))
