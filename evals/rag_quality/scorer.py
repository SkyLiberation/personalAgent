"""Scoring: turn (case, run output) pairs into per-case and aggregate reports.

The scorer consumes only :class:`RunOutput` (the thin scoreable projection),
never the live pipeline, so every metric is reproducible from serialized run
data and unit-testable with hand-built fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import RagEvalCase, RunOutput
from .metrics import (
    answer_relevance,
    claim_entailment_accuracy,
    context_precision,
    contrastive_coverage,
    faithfulness,
    ndcg_at_k,
    recall_at_k,
)


@dataclass(frozen=True)
class CaseScore:
    case_id: str
    recall_5: float
    ndcg_5: float
    context_precision: float
    answer_relevance: float
    faithfulness: float
    claim_accuracy: float
    contrastive_coverage: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


def score_case(case: RagEvalCase, run: RunOutput) -> CaseScore:
    gold = set(case.gold_evidence_ids)
    return CaseScore(
        case_id=case.id,
        recall_5=recall_at_k(run.ranked_evidence_ids, gold, 5),
        ndcg_5=ndcg_at_k(run.ranked_evidence_ids, gold, 5),
        context_precision=context_precision(run.selected_evidence_ids, gold),
        answer_relevance=answer_relevance(run.answer, case.question, case.reference_answer),
        faithfulness=faithfulness(run.answer, run.selected_evidence_texts),
        claim_accuracy=claim_entailment_accuracy(run.claim_verdicts, case.gold_claim_verdicts),
        contrastive_coverage=contrastive_coverage(
            case.claims_needing_contrast, run.counter_evidence_found,
        ),
    )


_METRIC_NAMES = (
    "recall_5", "ndcg_5", "context_precision",
    "answer_relevance", "faithfulness", "claim_accuracy", "contrastive_coverage",
)


@dataclass(frozen=True)
class RagQualityReport:
    """Aggregate (mean) of every metric across all scored cases."""

    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[CaseScore] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "num_cases": self.num_cases,
            "means": self.means,
            "per_case": [c.as_dict() for c in self.per_case],
        }

    def summary(self) -> str:
        lines = [f"RAG Quality Report ({self.num_cases} cases)"]
        for name in _METRIC_NAMES:
            lines.append(f"  {name:<20} {self.means.get(name, 0.0):.4f}")
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
        """Return a list of regression failures (empty = gate passes)."""
        failures: list[str] = []
        for name, floor in thresholds.items():
            actual = self.means.get(name, 0.0)
            if actual < floor:
                failures.append(f"{name}={actual:.4f} < threshold {floor:.4f}")
        return failures


def aggregate(scores: list[CaseScore]) -> RagQualityReport:
    n = len(scores)
    if n == 0:
        return RagQualityReport(num_cases=0, means=dict.fromkeys(_METRIC_NAMES, 0.0))
    means = {
        name: round(sum(getattr(s, name) for s in scores) / n, 4)
        for name in _METRIC_NAMES
    }
    return RagQualityReport(num_cases=n, means=means, per_case=scores)


def score_all(cases: list[RagEvalCase], runs: dict[str, RunOutput]) -> RagQualityReport:
    """Score every case that has a matching run output (keyed by case id)."""
    scores = [score_case(case, runs[case.id]) for case in cases if case.id in runs]
    return aggregate(scores)
