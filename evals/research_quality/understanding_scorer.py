"""Scoring for Research request-understanding evals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .understanding_dataset import (
    ResearchUnderstandingEvalCase,
    ResearchUnderstandingRunOutput,
)


@dataclass(frozen=True)
class ResearchUnderstandingCaseScore:
    case_id: str
    topic_term_coverage: float
    topic_control_term_absence: float
    instruction_term_coverage: float
    max_items_accuracy: float
    research_type_accuracy: float
    evidence_requirement_accuracy: float
    query_intent_coverage: float
    query_subject_coverage: float
    overall_score: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


_METRIC_NAMES = (
    "topic_term_coverage",
    "topic_control_term_absence",
    "instruction_term_coverage",
    "max_items_accuracy",
    "research_type_accuracy",
    "evidence_requirement_accuracy",
    "query_intent_coverage",
    "query_subject_coverage",
    "overall_score",
)


@dataclass(frozen=True)
class ResearchUnderstandingReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ResearchUnderstandingCaseScore] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Research Understanding Report ({self.num_cases} cases)"]
        for name in _METRIC_NAMES:
            lines.append(f"  {name:<32} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def score_understanding_case(
    case: ResearchUnderstandingEvalCase,
    output: ResearchUnderstandingRunOutput,
) -> ResearchUnderstandingCaseScore:
    topic_term_coverage = _term_coverage(output.topic, case.expected_topic_terms)
    topic_control_term_absence = _absence_score(output.topic, case.forbidden_topic_terms)
    instruction_term_coverage = _term_coverage(
        output.instructions,
        case.expected_instruction_terms,
    )
    max_items_accuracy = (
        1.0
        if case.expected_max_items is None
        or output.max_items == case.expected_max_items
        else 0.0
    )
    research_type_accuracy = (
        1.0
        if _matches_expected_or_acceptable(
            output.research_type,
            case.expected_research_type,
            case.acceptable_research_types,
        )
        else 0.0
    )
    evidence_requirement_accuracy = (
        1.0
        if _matches_expected_or_acceptable(
            output.evidence_requirement,
            case.expected_evidence_requirement,
            case.acceptable_evidence_requirements,
        )
        else 0.0
    )
    query_intent_coverage = _list_coverage(
        output.query_intents,
        case.expected_query_intents,
    )
    query_subject_coverage = _query_subject_coverage(
        output.query_texts,
        case.expected_topic_terms,
    )
    overall_score = round(sum([
        topic_term_coverage,
        topic_control_term_absence,
        instruction_term_coverage,
        max_items_accuracy,
        research_type_accuracy,
        evidence_requirement_accuracy,
        query_intent_coverage,
        query_subject_coverage,
    ]) / 8, 4)
    return ResearchUnderstandingCaseScore(
        case_id=case.id,
        topic_term_coverage=round(topic_term_coverage, 4),
        topic_control_term_absence=round(topic_control_term_absence, 4),
        instruction_term_coverage=round(instruction_term_coverage, 4),
        max_items_accuracy=max_items_accuracy,
        research_type_accuracy=research_type_accuracy,
        evidence_requirement_accuracy=evidence_requirement_accuracy,
        query_intent_coverage=round(query_intent_coverage, 4),
        query_subject_coverage=round(query_subject_coverage, 4),
        overall_score=overall_score,
    )


def score_understanding_all(
    cases: list[ResearchUnderstandingEvalCase],
    outputs: dict[str, ResearchUnderstandingRunOutput],
) -> ResearchUnderstandingReport:
    scores = [
        score_understanding_case(case, outputs[case.id])
        for case in cases
        if case.id in outputs
    ]
    if not scores:
        return ResearchUnderstandingReport(
            num_cases=0,
            means=dict.fromkeys(_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _METRIC_NAMES
    }
    return ResearchUnderstandingReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def _term_coverage(text: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lowered = text.lower()
    return sum(1 for term in terms if term.lower() in lowered) / len(terms)


def _matches_expected_or_acceptable(
    actual: str,
    expected: str,
    acceptable: list[str],
) -> bool:
    allowed = {value for value in [expected, *acceptable] if value}
    return not allowed or actual in allowed


def _absence_score(text: str, terms: list[str]) -> float:
    if not terms:
        return 1.0
    lowered = text.lower()
    return sum(1 for term in terms if term.lower() not in lowered) / len(terms)


def _list_coverage(values: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    lowered = {value.lower() for value in values}
    return sum(1 for item in expected if item.lower() in lowered) / len(expected)


def _query_subject_coverage(query_texts: list[str], topic_terms: list[str]) -> float:
    if not topic_terms:
        return 1.0
    if not query_texts:
        return 0.0
    return sum(
        1 for query in query_texts
        if all(term.lower() in query.lower() for term in topic_terms)
    ) / len(query_texts)
