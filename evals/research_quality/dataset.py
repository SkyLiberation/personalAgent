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
    mock_understanding: dict[str, Any] = field(default_factory=dict)
    expected_understanding_topic: str = ""
    expected_understanding_instruction_terms: list[str] = field(default_factory=list)
    expected_understanding_max_items: int | None = None
    expected_policy_type: str = ""
    expected_source_count: int | None = None
    min_iterations: int | None = None
    expected_query_plan_terms: list[list[str]] = field(default_factory=list)
    expected_query_terms: list[list[str]] = field(default_factory=list)
    expected_decision_phases: list[str] = field(default_factory=list)
    expected_gap_types: list[str] = field(default_factory=list)
    expected_stop_reason_terms: list[str] = field(default_factory=list)
    expected_satisfaction_should_continue: bool | None = None
    min_satisfaction_coverage_score: float | None = None
    min_satisfaction_confidence_score: float | None = None
    max_satisfaction_marginal_gain: float | None = None
    expected_satisfaction_gap_types: list[str] = field(default_factory=list)
    expected_stage_names: list[str] = field(default_factory=list)
    expected_tool_names: list[str] = field(default_factory=list)
    expected_events: list[ExpectedResearchEvent] = field(default_factory=list)
    expected_digest_title_terms: list[list[str]] = field(default_factory=list)
    expected_claim_support_levels: list[str] = field(default_factory=list)


@dataclass
class ResearchEventQualityRunOutput:
    source_count: int = 0
    iteration_count: int = 0
    understood_topic: str = ""
    understood_instructions: str = ""
    understood_max_items: int = 0
    policy_type: str = ""
    query_plan: list[str] = field(default_factory=list)
    query_history: list[str] = field(default_factory=list)
    decision_statuses: list[str] = field(default_factory=list)
    decision_phases: list[str] = field(default_factory=list)
    gap_types: list[str] = field(default_factory=list)
    stop_reason: str = ""
    satisfaction_recorded: bool = False
    satisfaction_should_continue: bool | None = None
    satisfaction_coverage_score: float = 0.0
    satisfaction_confidence_score: float = 0.0
    satisfaction_marginal_gain: float = 0.0
    satisfaction_gap_types: list[str] = field(default_factory=list)
    stage_names: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    source_trace_rate: float = 0.0
    decision_elapsed_rate: float = 0.0
    event_frame_rate: float = 0.0
    event_source_trace_rate: float = 0.0
    claim_support_rate: float = 0.0
    claim_evidence_span_rate: float = 0.0
    event_titles: list[str] = field(default_factory=list)
    events: list[Any] = field(default_factory=list)
    digest_titles: list[str] = field(default_factory=list)
    digest_items: list[Any] = field(default_factory=list)
    claim_support_levels: list[str] = field(default_factory=list)


def build_research_event_quality_run_output(
    *,
    completed: Any,
    state: Any,
    sources: list[Any],
    events: list[Any],
    digest: Any | None,
) -> ResearchEventQualityRunOutput:
    decisions = list(getattr(state, "decisions", []) or [])
    observed_decisions = [
        decision for decision in decisions
        if getattr(decision, "status", "planned") != "planned"
    ]
    executed_search_decisions = [
        decision for decision in observed_decisions
        if getattr(decision, "action", "") == "search_web"
        and getattr(decision, "status", "") == "executed"
    ]
    digest_items = list(getattr(digest, "items", []) or []) if digest is not None else []
    satisfaction = getattr(state, "satisfaction", None)
    return ResearchEventQualityRunOutput(
        source_count=getattr(completed, "source_count", 0),
        iteration_count=getattr(state, "iteration_count", 0),
        understood_topic=str(getattr(state, "topic", "")),
        understood_instructions=str(getattr(state, "instructions", "")),
        understood_max_items=int(getattr(state, "max_items", 0)),
        policy_type=str(getattr(getattr(state, "policy", None), "research_type", "")),
        query_plan=[
            getattr(query, "query", str(query))
            for query in (getattr(state, "query_plan", []) or [])
        ],
        query_history=list(getattr(state, "query_history", []) or []),
        decision_statuses=[
            str(getattr(decision, "status", ""))
            for decision in observed_decisions
        ],
        decision_phases=[
            str(getattr(decision, "query_phase", ""))
            for decision in executed_search_decisions
        ],
        gap_types=[
            str(getattr(gap, "type", ""))
            for gap in (getattr(state, "evidence_gaps", []) or [])
        ],
        stop_reason=str(getattr(state, "stop_reason", "")),
        satisfaction_recorded=satisfaction is not None,
        satisfaction_should_continue=(
            bool(getattr(satisfaction, "should_continue"))
            if satisfaction is not None else None
        ),
        satisfaction_coverage_score=float(
            getattr(satisfaction, "coverage_score", 0.0)
        ),
        satisfaction_confidence_score=float(
            getattr(satisfaction, "confidence_score", 0.0)
        ),
        satisfaction_marginal_gain=float(
            getattr(satisfaction, "marginal_gain", 0.0)
        ),
        satisfaction_gap_types=[
            str(getattr(gap, "type", ""))
            for gap in (
                getattr(satisfaction, "remaining_critical_gaps", [])
                if satisfaction is not None else []
            )
        ],
        stage_names=[
            str(getattr(timing, "stage", ""))
            for timing in (getattr(state, "stage_timings", []) or [])
        ],
        tool_names=[
            str(getattr(trace, "tool_name", ""))
            for trace in (getattr(state, "tool_call_traces", []) or [])
        ],
        source_trace_rate=_rate(
            sources,
            lambda source: bool(
                getattr(source, "decision_id", None)
                and getattr(source, "query", "")
            ),
        ),
        decision_elapsed_rate=_rate(
            executed_search_decisions,
            lambda decision: bool(
                getattr(decision, "started_at", None)
                and getattr(decision, "completed_at", None)
            ),
        ),
        event_frame_rate=_rate(
            events,
            lambda event: _event_has_frame(event),
        ),
        event_source_trace_rate=_rate(
            events,
            lambda event: bool(getattr(event, "source_ids", []) or []),
        ),
        claim_support_rate=_claim_rate(
            digest_items,
            lambda claim: getattr(claim, "support_level", "") in {
                "supported",
                "partially_supported",
            },
        ),
        claim_evidence_span_rate=_claim_rate(
            digest_items,
            lambda claim: bool(getattr(claim, "evidence_spans", []) or []),
            supported_only=True,
        ),
        event_titles=[str(getattr(event, "title", "")) for event in events],
        events=events,
        digest_titles=[
            str(getattr(item, "title", ""))
            for item in digest_items
        ],
        digest_items=digest_items,
        claim_support_levels=[
            str(getattr(claim, "support_level", ""))
            for item in digest_items
            for claim in (getattr(item, "claims", []) or [])
        ],
    )


def _rate(items: list[Any], predicate) -> float:
    if not items:
        return 1.0
    return sum(1 for item in items if predicate(item)) / len(items)


def _event_has_frame(event: Any) -> bool:
    frame = getattr(event, "frame", None)
    if frame is None:
        return False
    return bool(
        getattr(frame, "actor", "")
        or getattr(frame, "action", "")
        or getattr(frame, "object", "")
        or getattr(frame, "event_type", "")
    )


def _claim_rate(
    digest_items: list[Any],
    predicate,
    *,
    supported_only: bool = False,
) -> float:
    claims: list[Any] = []
    for item in digest_items:
        for claim in (getattr(item, "claims", []) or []):
            if supported_only and getattr(claim, "support_level", "") not in {
                "supported",
                "partially_supported",
            }:
                continue
            claims.append(claim)
    if not claims:
        return 1.0 if not digest_items else 0.0
    return sum(1 for claim in claims if predicate(claim)) / len(claims)


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
                mock_understanding=dict(item.get("mock_understanding") or {}),
                expected_understanding_topic=str(
                    item.get("expected_understanding_topic") or ""
                ),
                expected_understanding_instruction_terms=[
                    str(term)
                    for term in item.get("expected_understanding_instruction_terms", [])
                ],
                expected_understanding_max_items=(
                    int(item["expected_understanding_max_items"])
                    if "expected_understanding_max_items" in item else None
                ),
                expected_policy_type=str(item.get("expected_policy_type") or ""),
                expected_source_count=(
                    int(item["expected_source_count"])
                    if "expected_source_count" in item else None
                ),
                min_iterations=(
                    int(item["min_iterations"])
                    if "min_iterations" in item else None
                ),
                expected_query_plan_terms=[
                    [str(term) for term in terms]
                    for terms in item.get("expected_query_plan_terms", [])
                ],
                expected_query_terms=[
                    [str(term) for term in terms]
                    for terms in item.get("expected_query_terms", [])
                ],
                expected_decision_phases=[
                    str(phase) for phase in item.get("expected_decision_phases", [])
                ],
                expected_gap_types=[
                    str(gap_type) for gap_type in item.get("expected_gap_types", [])
                ],
                expected_stop_reason_terms=[
                    str(term) for term in item.get("expected_stop_reason_terms", [])
                ],
                expected_satisfaction_should_continue=(
                    bool(item["expected_satisfaction_should_continue"])
                    if "expected_satisfaction_should_continue" in item else None
                ),
                min_satisfaction_coverage_score=(
                    float(item["min_satisfaction_coverage_score"])
                    if "min_satisfaction_coverage_score" in item else None
                ),
                min_satisfaction_confidence_score=(
                    float(item["min_satisfaction_confidence_score"])
                    if "min_satisfaction_confidence_score" in item else None
                ),
                max_satisfaction_marginal_gain=(
                    float(item["max_satisfaction_marginal_gain"])
                    if "max_satisfaction_marginal_gain" in item else None
                ),
                expected_satisfaction_gap_types=[
                    str(gap_type)
                    for gap_type in item.get(
                        "expected_satisfaction_gap_types", []
                    )
                ],
                expected_stage_names=[
                    str(stage) for stage in item.get("expected_stage_names", [])
                ],
                expected_tool_names=[
                    str(tool) for tool in item.get("expected_tool_names", [])
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
                expected_claim_support_levels=[
                    str(level)
                    for level in item.get("expected_claim_support_levels", [])
                ],
            )
        )
    return cases


def default_event_quality_cases_path() -> Path:
    return Path(__file__).parent / "event_quality_cases.json"
