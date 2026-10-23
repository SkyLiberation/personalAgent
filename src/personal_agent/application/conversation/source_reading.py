"""Derive source coverage from the execution windows visible to Conversation."""

from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from personal_agent.application.capture.web_source import (
    WEB_SOURCE_FORMAT,
    WebReadOutput,
)
from personal_agent.capabilities.contracts.verification import SourceReadingState
from personal_agent.kernel.contracts.resource import ResourceRef
from personal_agent.application.artifacts.models import ContentDigest, TextPosition

from .context_materialization import (
    ARTIFACT_OUTPUT_CAPABILITIES,
    select_visible_successful_observations,
)
from .models import ActionObservation, ArtifactSourceInput, InteractionInput


class SourceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    resource_ref: ResourceRef
    source_url: str | None = None
    document_kind: Literal["source_text", "tool_result"] = "source_text"
    total_lines: int | None = Field(default=None, ge=0)


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
    content_digest: ContentDigest | None = None
    eof_position: TextPosition | None = None


def source_metadata_by_resource(
    observations: Iterable[InteractionInput],
) -> dict[ResourceRef, SourceMetadata]:
    """Resolve source identity once from already-visible successful execution facts."""
    observations = tuple(observations)
    sources: dict[ResourceRef, SourceMetadata] = {}
    resources = {}
    for item in observations:
        if isinstance(item, ArtifactSourceInput):
            previous = resources.setdefault(item.resource.resource_ref, item.resource)
            if previous != item.resource:
                raise ValueError("conflicting metadata for one Artifact version")
            sources[item.resource.resource_ref] = SourceMetadata(
                resource_ref=item.resource.resource_ref
            )
    # Explicit execution bindings retain their known source kind/URL over generic metadata.
    explicit: dict[ResourceRef, SourceMetadata] = {}
    for item in observations:
        if not isinstance(item, ActionObservation) or item.status != "succeeded":
            continue
        if item.capability_id in ARTIFACT_OUTPUT_CAPABILITIES:
            continue
        retrieval = item.payload.get("retrieval")
        if not isinstance(retrieval, dict) or "resource_ref" not in retrieval:
            continue
        binding = OffloadedSource.model_validate(retrieval)
        data = item.payload.get("data")
        source_url = (
            WebReadOutput.model_validate(data).source_url
            if isinstance(data, dict) and data.get("format") == WEB_SOURCE_FORMAT
            else ""
        )
        entry = SourceMetadata(
            resource_ref=binding.resource_ref,
            source_url=source_url or None,
            document_kind="source_text" if source_url else "tool_result",
            total_lines=binding.total_lines,
        )
        previous = explicit.get(binding.resource_ref)
        if previous is not None and (
            previous.document_kind != entry.document_kind
            or previous.source_url
            and entry.source_url
            and previous.source_url != entry.source_url
            or previous.total_lines is not None
            and entry.total_lines is not None
            and previous.total_lines != entry.total_lines
        ):
            raise ValueError("inconsistent metadata for one source version")
        if previous is not None:
            entry = entry.model_copy(
                update={
                    "source_url": entry.source_url or previous.source_url,
                    "total_lines": entry.total_lines
                    if entry.total_lines is not None
                    else previous.total_lines,
                }
            )
        explicit[binding.resource_ref] = entry
    sources.update(explicit)
    return sources


def materialize_source_reading_state(
    inputs: Iterable[InteractionInput],
    *,
    verifier_capability_id: str = "verify_interaction_draft",
) -> tuple[SourceReadingState, ...]:
    inputs = tuple(inputs)
    observations = select_visible_successful_observations(
        inputs,
        excluded_capability_ids=frozenset({verifier_capability_id}),
    )
    sources = source_metadata_by_resource((*inputs, *observations))
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
        metadata = sources[window.resource_ref]
        total = metadata.total_lines
        if total is not None and total != window.total_lines:
            raise ValueError("source length changed within one resource version")
        if any(line.line > window.total_lines for line in window.lines):
            raise ValueError("returned line exceeds source length")
        sources[window.resource_ref] = metadata.model_copy(
            update={"total_lines": window.total_lines}
        )
        for line in window.lines:
            length = (
                line.line_length if line.line_length is not None else len(line.text)
            )
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
            resource_ref=ref,
            source_url=metadata.source_url or "",
            returned_unique_segments=len(seen[ref]),
            total_segments=metadata.total_lines,
            fully_read=metadata.total_lines is not None
            and len(seen[ref]) == metadata.total_lines,
        )
        for ref, metadata in sources.items()
    )
