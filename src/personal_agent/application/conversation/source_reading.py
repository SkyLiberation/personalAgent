"""Derive source coverage from the execution windows visible to Conversation."""

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture.web_source import WEB_SOURCE_FORMAT, WebReadOutput
from personal_agent.capabilities.contracts.verification import SourceReadingState
from personal_agent.kernel.contracts.resource import ResourceRef

from .context_materialization import ARTIFACT_OUTPUT_CAPABILITIES, select_visible_successful_observations
from .models import ActionObservation, InteractionInput


class OffloadedSource(BaseModel):
    """Projection of the execution-owned retrieval envelope; unknown length is incomplete."""

    resource_ref: ResourceRef
    total_lines: int | None = Field(default=None, ge=0)


class ReturnedSourceLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line: int = Field(ge=1)
    text: str
    start_column: int = Field(default=1, ge=1)
    line_length: int | None = Field(default=None, ge=0)


class SourceReadWindow(BaseModel):
    """Version and line facts of a successful read; surrounding tool metadata is ignored."""

    resource_ref: ResourceRef
    total_lines: int = Field(ge=0)
    lines: tuple[ReturnedSourceLine, ...]


def source_metadata_by_resource(
    observations: Iterable[ActionObservation],
) -> dict[ResourceRef, tuple[str, int | None]]:
    """Resolve source identity once from already-visible successful execution facts."""
    sources: dict[ResourceRef, tuple[str, int | None]] = {}
    for item in observations:
        if item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES:
            continue
        retrieval = item.payload.get("retrieval")
        if not isinstance(retrieval, dict) or "resource_ref" not in retrieval:
            continue
        binding = OffloadedSource.model_validate(retrieval)
        data = item.payload.get("data")
        source_url = (
            WebReadOutput.model_validate(data).source_url
            if isinstance(data, dict) and data.get("format") == WEB_SOURCE_FORMAT else ""
        )
        entry = (source_url, binding.total_lines)
        if binding.resource_ref in sources and sources[binding.resource_ref] != entry:
            raise ValueError("inconsistent metadata for one source version")
        sources[binding.resource_ref] = entry
    return sources


def materialize_source_reading_state(
    inputs: Iterable[InteractionInput],
    *,
    verifier_capability_id: str = "verify_interaction_draft",
) -> tuple[SourceReadingState, ...]:
    observations = select_visible_successful_observations(
        inputs, excluded_capability_ids=frozenset({verifier_capability_id}),
    )
    sources = source_metadata_by_resource(observations)
    seen: dict[ResourceRef, set[int]] = {ref: set() for ref in sources}
    ranges: dict[tuple[ResourceRef, int], list[tuple[int, int]]] = {}
    for item in observations:
        if item.capability_id not in ARTIFACT_OUTPUT_CAPABILITIES:
            continue
        # A lossy display does not prove any of its original lines was fully shown.
        if item.payload.get("retrieval"):
            continue
        window = SourceReadWindow.model_validate(item.payload)
        if window.resource_ref not in sources:
            raise ValueError("read window has no visible source version binding")
        url, total = sources[window.resource_ref]
        if total is not None and total != window.total_lines:
            raise ValueError("source length changed within one resource version")
        if any(line.line > window.total_lines for line in window.lines):
            raise ValueError("returned line exceeds source length")
        sources[window.resource_ref] = (url, window.total_lines)
        for line in window.lines:
            length = line.line_length if line.line_length is not None else len(line.text)
            start = line.start_column - 1
            end = start + len(line.text)
            if end > length or start > length:
                raise ValueError("returned text exceeds source line length")
            intervals = ranges.setdefault((window.resource_ref, line.line), [])
            intervals.append((start, end))
            covered = 0
            for left, right in sorted(intervals):
                if left > covered:
                    break
                covered = max(covered, right)
            if covered == length:
                seen[window.resource_ref].add(line.line)
    return tuple(
        SourceReadingState(
            resource_ref=ref, source_url=url, returned_unique_segments=len(seen[ref]),
            total_segments=total, fully_read=bool(total) and len(seen[ref]) == total,
        ) for ref, (url, total) in sources.items()
    )
