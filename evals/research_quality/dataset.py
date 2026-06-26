"""Dataset model + loader for Research capability golden cases."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExpectedResearchEvent:
    title_terms: list[str] = field(default_factory=list)
    expected_status: str | None = None
    min_sources: int = 1
    requires_primary_source: bool = False
    min_personal_relevance: float | None = None


@dataclass(frozen=True)
class ResearchEventQualityEvalCase:
    id: str
    description: str
    topic: str
    instructions: str = ""
    max_items: int = 5
    search_results: list[dict[str, Any]] = field(default_factory=list)
    search_results_by_query: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    fulltext_by_url: dict[str, str] = field(default_factory=dict)
    graph_matches_by_title: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    event_frames_by_title: dict[str, dict[str, Any]] = field(default_factory=dict)
    expected_source_count: int | None = None
    min_iterations: int | None = None
    expected_query_terms: list[list[str]] = field(default_factory=list)
    expected_gap_types: list[str] = field(default_factory=list)
    expected_stop_reason_terms: list[str] = field(default_factory=list)
    expected_events: list[ExpectedResearchEvent] = field(default_factory=list)
    expected_digest_title_terms: list[list[str]] = field(default_factory=list)


@dataclass
class ResearchEventQualityRunOutput:
    source_count: int = 0
    iteration_count: int = 0
    query_history: list[str] = field(default_factory=list)
    gap_types: list[str] = field(default_factory=list)
    stop_reason: str = ""
    event_titles: list[str] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    digest_titles: list[str] = field(default_factory=list)


def load_event_quality_cases(path: str | Path) -> list[ResearchEventQualityEvalCase]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases: list[ResearchEventQualityEvalCase] = []
    for item in raw:
        cases.append(
            ResearchEventQualityEvalCase(
                id=str(item["id"]),
                description=str(item.get("description", "")),
                topic=str(item["topic"]),
                instructions=str(item.get("instructions", "")),
                max_items=int(item.get("max_items", 5)),
                search_results=[
                    dict(result) for result in item.get("search_results", [])
                ],
                search_results_by_query={
                    str(key): [dict(result) for result in results]
                    for key, results in (
                        item.get("search_results_by_query") or {}
                    ).items()
                },
                fulltext_by_url={
                    str(key): str(value)
                    for key, value in (item.get("fulltext_by_url") or {}).items()
                },
                graph_matches_by_title={
                    str(key): [
                        dict(match) for match in matches
                    ]
                    for key, matches in (
                        item.get("graph_matches_by_title") or {}
                    ).items()
                },
                event_frames_by_title={
                    str(key): dict(value)
                    for key, value in (
                        item.get("event_frames_by_title") or {}
                    ).items()
                },
                expected_source_count=(
                    int(item["expected_source_count"])
                    if "expected_source_count" in item else None
                ),
                min_iterations=(
                    int(item["min_iterations"])
                    if "min_iterations" in item else None
                ),
                expected_query_terms=[
                    [str(term) for term in terms]
                    for terms in item.get("expected_query_terms", [])
                ],
                expected_gap_types=[
                    str(gap_type) for gap_type in item.get("expected_gap_types", [])
                ],
                expected_stop_reason_terms=[
                    str(term) for term in item.get("expected_stop_reason_terms", [])
                ],
                expected_events=[
                    ExpectedResearchEvent(
                        title_terms=[
                            str(term) for term in event.get("title_terms", [])
                        ],
                        expected_status=event.get("expected_status"),
                        min_sources=int(event.get("min_sources", 1)),
                        requires_primary_source=bool(
                            event.get("requires_primary_source", False)
                        ),
                        min_personal_relevance=(
                            float(event["min_personal_relevance"])
                            if "min_personal_relevance" in event else None
                        ),
                    )
                    for event in item.get("expected_events", [])
                ],
                expected_digest_title_terms=[
                    [str(term) for term in terms]
                    for terms in item.get("expected_digest_title_terms", [])
                ],
            )
        )
    return cases


def default_event_quality_cases_path() -> Path:
    return Path(__file__).parent / "event_quality_cases.json"
