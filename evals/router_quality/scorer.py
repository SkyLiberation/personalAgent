"""Scoring: turn (case, router run output) pairs into per-case and aggregate
reports. Mirrors the RAG-quality scorer's shape so both harnesses read alike.

The scorer consumes only :class:`RouterRunOutput`, never the live router, so
every metric is reproducible from serialized decisions and unit-testable with
hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import RouterEvalCase, RouterRunOutput
from .metrics import (
    clarify_field_precision,
    intent_sequence_exact,
    intent_set_f1,
    outcome_correct,
)


@dataclass(frozen=True)
class RouterCaseScore:
    case_id: str
    outcome_accuracy: float
    intent_f1: float
    intent_sequence_exact: float
    clarify_field_precision: float
    latency_ms: float
    llm_call_count: float
    input_tokens: float
    output_tokens: float
    total_tokens: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_case(case: RouterEvalCase, run: RouterRunOutput) -> RouterCaseScore:
    return RouterCaseScore(
        case_id=case.id,
        outcome_accuracy=outcome_correct(run.outcome, case.expected_outcome),
        intent_f1=intent_set_f1(run.intents, case.expected_intents),
        intent_sequence_exact=intent_sequence_exact(run.intents, case.expected_intents),
        clarify_field_precision=clarify_field_precision(
            run.missing_information, case.expected_missing_info,
        ),
        latency_ms=run.latency_ms,
        llm_call_count=float(run.llm_call_count),
        input_tokens=float(run.input_tokens),
        output_tokens=float(run.output_tokens),
        total_tokens=float(run.total_tokens),
    )


_METRIC_NAMES = (
    "outcome_accuracy", "intent_f1", "intent_sequence_exact", "clarify_field_precision",
    "latency_ms", "llm_call_count", "input_tokens", "output_tokens", "total_tokens",
    "latency_p95_ms", "total_tokens_p95",
)


@dataclass(frozen=True)
class RouterQualityReport:
    """Aggregate (mean) of every metric across all scored cases."""

    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[RouterCaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [c.as_dict() for c in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"Router Quality Report ({self.num_cases} cases)"]
        for name in _METRIC_NAMES:
            lines.append(f"  {name:<24} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        """Return a list of regression failures (empty = gate passes)."""
        failures: list[str] = []
        for name, floor in thresholds.items():
            if name.endswith("_max"):
                metric = name[:-4]
                actual = self.means.get(metric, 0.0)
                if actual > floor:
                    failures.append(f"{metric}={actual:.4f} > ceiling {floor:.4f}")
                continue
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate(scores: list[RouterCaseScore]) -> RouterQualityReport:
    n = len(scores)
    if n == 0:
        return RouterQualityReport(num_cases=0, means=dict.fromkeys(_METRIC_NAMES, 0.0))
    base_names = tuple(name for name in _METRIC_NAMES if name not in {
        "latency_p95_ms", "total_tokens_p95",
    })
    means = {
        name: round(sum(getattr(s, name) for s in scores) / n, 4)
        for name in base_names
    }
    means["latency_p95_ms"] = _percentile([s.latency_ms for s in scores], 0.95)
    means["total_tokens_p95"] = _percentile([s.total_tokens for s in scores], 0.95)
    return RouterQualityReport(num_cases=n, means=means, per_case=scores)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.999999)))
    return round(ordered[index], 4)


def score_all(
    cases: list[RouterEvalCase], runs: dict[str, RouterRunOutput],
) -> RouterQualityReport:
    """Score every case that has a matching run output (keyed by case id)."""
    scores = [score_case(case, runs[case.id]) for case in cases if case.id in runs]
    return aggregate(scores)
