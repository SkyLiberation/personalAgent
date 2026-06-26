"""Scoring for Research workflow golden cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import (
    ExpectedResearchEvent,
    ResearchEventQualityEvalCase,
    ResearchEventQualityRunOutput,
)


@dataclass(frozen=True)
class ResearchEventQualityCaseScore:
    case_id: str
    source_count_exact: float
    min_iterations_met: float
    query_coverage: float
    gap_coverage: float
    stop_reason_match: float
    event_recall: float
    event_precision: float
    status_accuracy: float
    source_support_accuracy: float
    personal_relevance_accuracy: float
    digest_coverage: float
    primary_source_rate: float
    overall_score: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_event_quality_case(
    case: ResearchEventQualityEvalCase,
    run: ResearchEventQualityRunOutput,
) -> ResearchEventQualityCaseScore:
    matched_events = [
        _match_expected_event(expected, run.events)
        for expected in case.expected_events
    ]
    matched_actual_ids = {
        id(event)
        for event in matched_events
        if event is not None
    }
    source_count_exact = (
        1.0
        if case.expected_source_count is None
        or run.source_count == case.expected_source_count
        else 0.0
    )
    min_iterations_met = (
        1.0
        if case.min_iterations is None
        or run.iteration_count >= case.min_iterations
        else 0.0
    )
    query_coverage = _text_list_coverage(
        run.query_history,
        case.expected_query_terms,
    )
    gap_coverage = (
        sum(1 for gap_type in case.expected_gap_types if gap_type in run.gap_types)
        / len(case.expected_gap_types)
        if case.expected_gap_types else 1.0
    )
    stop_reason_match = (
        1.0
        if not case.expected_stop_reason_terms
        or _contains_terms(run.stop_reason, case.expected_stop_reason_terms)
        else 0.0
    )
    event_recall = (
        sum(1 for event in matched_events if event is not None)
        / len(case.expected_events)
        if case.expected_events else 1.0
    )
    event_precision = (
        len(matched_actual_ids) / len(run.events)
        if run.events else (1.0 if not case.expected_events else 0.0)
    )
    status_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        lambda expected, event: (
            expected.expected_status is None
            or getattr(event, "status", None) == expected.expected_status
        ),
    )
    source_support_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        _source_support_matches,
    )
    personal_relevance_accuracy = _expected_event_average(
        case.expected_events,
        matched_events,
        _personal_relevance_matches,
    )
    digest_coverage = _digest_coverage(
        run.digest_titles,
        case.expected_digest_title_terms,
    )
    primary_source_rate = (
        sum(1 for event in run.events if _has_primary_source(event)) / len(run.events)
        if run.events else 1.0
    )
    overall_score = round(
        source_count_exact * 0.07
        + min_iterations_met * 0.07
        + query_coverage * 0.1
        + gap_coverage * 0.07
        + stop_reason_match * 0.04
        + event_recall * 0.18
        + event_precision * 0.1
        + status_accuracy * 0.1
        + source_support_accuracy * 0.1
        + personal_relevance_accuracy * 0.07
        + digest_coverage * 0.1,
        4,
    )
    return ResearchEventQualityCaseScore(
        case_id=case.id,
        source_count_exact=source_count_exact,
        min_iterations_met=min_iterations_met,
        query_coverage=round(query_coverage, 4),
        gap_coverage=round(gap_coverage, 4),
        stop_reason_match=stop_reason_match,
        event_recall=round(event_recall, 4),
        event_precision=round(event_precision, 4),
        status_accuracy=round(status_accuracy, 4),
        source_support_accuracy=round(source_support_accuracy, 4),
        personal_relevance_accuracy=round(personal_relevance_accuracy, 4),
        digest_coverage=round(digest_coverage, 4),
        primary_source_rate=round(primary_source_rate, 4),
        overall_score=overall_score,
    )


_EVENT_METRIC_NAMES = (
    "source_count_exact",
    "min_iterations_met",
    "query_coverage",
    "gap_coverage",
    "stop_reason_match",
    "event_recall",
    "event_precision",
    "status_accuracy",
    "source_support_accuracy",
    "personal_relevance_accuracy",
    "digest_coverage",
    "primary_source_rate",
    "overall_score",
)


@dataclass(frozen=True)
class ResearchEventQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ResearchEventQualityCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [score.as_dict() for score in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Research Event Quality Report ({self.num_cases} cases)"]
        for name in _EVENT_METRIC_NAMES:
            lines.append(f"  {name:<30} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate_event_quality(
    scores: list[ResearchEventQualityCaseScore],
) -> ResearchEventQualityReport:
    if not scores:
        return ResearchEventQualityReport(
            num_cases=0,
            means=dict.fromkeys(_EVENT_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _EVENT_METRIC_NAMES
    }
    return ResearchEventQualityReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def score_event_quality_all(
    cases: list[ResearchEventQualityEvalCase],
    runs: dict[str, ResearchEventQualityRunOutput],
) -> ResearchEventQualityReport:
    scores = [
        score_event_quality_case(case, runs[case.id])
        for case in cases
        if case.id in runs
    ]
    return aggregate_event_quality(scores)


def _match_expected_event(expected: ExpectedResearchEvent, events: list[object]):
    for event in events:
        if _contains_terms(getattr(event, "title", ""), expected.title_terms):
            return event
    return None


def _contains_terms(text: str, terms: list[str]) -> bool:
    normalized = text.lower()
    return all(term.lower() in normalized for term in terms)


def _expected_event_average(expected_events, matched_events, predicate) -> float:
    if not expected_events:
        return 1.0
    scores: list[float] = []
    for expected, event in zip(expected_events, matched_events, strict=False):
        if event is None:
            scores.append(0.0)
        else:
            scores.append(1.0 if predicate(expected, event) else 0.0)
    return sum(scores) / len(expected_events)


def _source_support_matches(expected: ExpectedResearchEvent, event) -> bool:
    sources = list(getattr(event, "sources", []) or [])
    if len(sources) < expected.min_sources:
        return False
    return not expected.requires_primary_source or _has_primary_source(event)


def _personal_relevance_matches(expected: ExpectedResearchEvent, event) -> bool:
    if expected.min_personal_relevance is None:
        return True
    relevance = getattr(event, "personal_relevance", None)
    score = getattr(relevance, "score", 0.0)
    return score >= expected.min_personal_relevance


def _has_primary_source(event) -> bool:
    return any(
        getattr(source, "source_type", "") in {"official", "paper"}
        for source in (getattr(event, "sources", []) or [])
    )


def _digest_coverage(digest_titles: list[str], expected_terms: list[list[str]]) -> float:
    if not expected_terms:
        return 1.0
    matched = sum(
        1
        for terms in expected_terms
        if any(_contains_terms(title, terms) for title in digest_titles)
    )
    return matched / len(expected_terms)


def _text_list_coverage(texts: list[str], expected_terms: list[list[str]]) -> float:
    if not expected_terms:
        return 1.0
    matched = sum(
        1
        for terms in expected_terms
        if any(_contains_terms(text, terms) for text in texts)
    )
    return matched / len(expected_terms)
