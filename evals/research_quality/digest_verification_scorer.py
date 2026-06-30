"""Scoring for Research digest claim-verification evals."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .digest_verification_dataset import (
    DigestVerificationEvalCase,
    DigestVerificationRunOutput,
)


@dataclass(frozen=True)
class DigestVerificationCaseScore:
    case_id: str
    item_count_accuracy: float
    no_major_update_accuracy: float
    run_status_accuracy: float
    confidence_label_accuracy: float
    claim_support_level_accuracy: float
    absent_claim_term_accuracy: float
    overall_score: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


_METRIC_NAMES = (
    "item_count_accuracy",
    "no_major_update_accuracy",
    "run_status_accuracy",
    "confidence_label_accuracy",
    "claim_support_level_accuracy",
    "absent_claim_term_accuracy",
    "overall_score",
)


@dataclass(frozen=True)
class DigestVerificationReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[DigestVerificationCaseScore] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Research Digest Verification Report ({self.num_cases} cases)"]
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


def score_digest_verification_case(
    case: DigestVerificationEvalCase,
    output: DigestVerificationRunOutput,
) -> DigestVerificationCaseScore:
    item_count_accuracy = 1.0 if output.item_count == case.expected_item_count else 0.0
    no_major_update_accuracy = (
        1.0
        if output.no_major_update == case.expected_no_major_update
        else 0.0
    )
    run_status_accuracy = (
        1.0
        if not case.expected_run_status
        or output.run_status == case.expected_run_status
        else 0.0
    )
    confidence_label_accuracy = _list_exact(
        output.confidence_labels,
        case.expected_confidence_labels,
    )
    claim_support_level_accuracy = _list_exact(
        output.claim_support_levels,
        case.expected_claim_support_levels,
    )
    absent_claim_term_accuracy = _absence_score(
        output.retained_claim_texts,
        case.expected_absent_claim_terms,
    )
    overall_score = round(sum([
        item_count_accuracy,
        no_major_update_accuracy,
        run_status_accuracy,
        confidence_label_accuracy,
        claim_support_level_accuracy,
        absent_claim_term_accuracy,
    ]) / 6, 4)
    return DigestVerificationCaseScore(
        case_id=case.id,
        item_count_accuracy=item_count_accuracy,
        no_major_update_accuracy=no_major_update_accuracy,
        run_status_accuracy=run_status_accuracy,
        confidence_label_accuracy=confidence_label_accuracy,
        claim_support_level_accuracy=claim_support_level_accuracy,
        absent_claim_term_accuracy=absent_claim_term_accuracy,
        overall_score=overall_score,
    )


def score_digest_verification_all(
    cases: list[DigestVerificationEvalCase],
    outputs: dict[str, DigestVerificationRunOutput],
) -> DigestVerificationReport:
    scores = [
        score_digest_verification_case(case, outputs[case.id])
        for case in cases
        if case.id in outputs
    ]
    if not scores:
        return DigestVerificationReport(
            num_cases=0,
            means=dict.fromkeys(_METRIC_NAMES, 0.0),
        )
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in _METRIC_NAMES
    }
    return DigestVerificationReport(
        num_cases=len(scores),
        means=means,
        per_case=scores,
    )


def _list_exact(actual: list[str], expected: list[str]) -> float:
    return 1.0 if actual == expected else 0.0


def _absence_score(texts: list[str], terms: list[str]) -> float:
    if not terms:
        return 1.0
    lowered = "\n".join(texts).lower()
    return sum(1 for term in terms if term.lower() not in lowered) / len(terms)
