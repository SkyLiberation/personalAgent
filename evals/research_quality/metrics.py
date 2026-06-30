from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


def scalar_exact(actual: object, expected: object) -> float:
    return 1.0 if actual == expected else 0.0


def ordered_sequence_exact(actual: Iterable[str], expected: Iterable[str]) -> float:
    return 1.0 if list(actual) == list(expected) else 0.0


def unordered_sequence_exact(actual: Iterable[str], expected: Iterable[str]) -> float:
    return 1.0 if sorted(actual) == sorted(expected) else 0.0


def keyed_list_map_exact(
    actual: dict[str, list[str]],
    expected: dict[str, list[str]],
    *,
    ordered: bool = True,
) -> float:
    for key, expected_values in expected.items():
        actual_values = actual.get(key, [])
        if ordered:
            if actual_values != expected_values:
                return 0.0
        elif sorted(actual_values) != sorted(expected_values):
            return 0.0
    return 1.0


def keyed_scalar_map_exact(
    actual: dict[str, str],
    expected: dict[str, str],
) -> float:
    return (
        1.0
        if all(actual.get(key) == value for key, value in expected.items())
        else 0.0
    )


@dataclass(frozen=True)
class ResearchQualityMetrics:
    event_recall: float
    event_precision: float
    deduplication_quality: float
    primary_source_rate: float
    uncertainty_calibration: float

    @property
    def score(self) -> float:
        return (
            self.event_recall * 0.25
            + self.event_precision * 0.25
            + self.deduplication_quality * 0.2
            + self.primary_source_rate * 0.15
            + self.uncertainty_calibration * 0.15
        )


def score_research_events(
    events,
    *,
    expected_keys: set[str],
    expected_uncertain_keys: set[str] | None = None,
) -> ResearchQualityMetrics:
    expected_uncertain_keys = expected_uncertain_keys or set()
    actual_keys = {event.canonical_key for event in events}
    true_positive = len(actual_keys & expected_keys)
    recall = true_positive / len(expected_keys) if expected_keys else 1.0
    precision = true_positive / len(actual_keys) if actual_keys else (1.0 if not expected_keys else 0.0)

    source_urls = [
        source.canonical_url
        for event in events
        for source in event.sources
    ]
    deduplication = len(set(source_urls)) / len(source_urls) if source_urls else 1.0
    primary_source_types = {
        "official",
        "docs",
        "github",
        "paper",
        "filing",
        "investor_relations",
        "transcript",
    }
    primary = sum(
        1 for event in events
        if any(source.source_type in primary_source_types for source in event.sources)
    )
    primary_rate = primary / len(events) if events else 1.0

    uncertainty_checks = [
        event.status == "uncertain"
        for event in events
        if event.canonical_key in expected_uncertain_keys
    ]
    uncertainty = (
        sum(uncertainty_checks) / len(uncertainty_checks)
        if uncertainty_checks else 1.0
    )
    return ResearchQualityMetrics(
        event_recall=recall,
        event_precision=precision,
        deduplication_quality=deduplication,
        primary_source_rate=primary_rate,
        uncertainty_calibration=uncertainty,
    )
