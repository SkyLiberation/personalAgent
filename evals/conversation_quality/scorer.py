"""Conversation-level scorer consuming only thin serialized projections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .dataset import ConversationEvalCase, ConversationRunOutput
from .metrics import (
    exact_match,
    ordered_subsequence,
    reference_recall,
    response_contains,
    resume_success,
    side_effect_accuracy,
    thread_continuity,
)


@dataclass(frozen=True)
class ConversationCaseScore:
    case_id: str
    turn_outcome_accuracy: float
    turn_intent_accuracy: float
    event_sequence_match: float
    context_retention: float
    response_grounding: float
    resume_success_rate: float
    thread_continuity: float
    side_effect_accuracy: float
    final_task_success: float
    latency_ms: float
    llm_call_count: float
    input_tokens: float
    output_tokens: float
    total_tokens: float

    def as_dict(self) -> dict[str, float | str]:
        return asdict(self)


_METRIC_NAMES = (
    "turn_outcome_accuracy",
    "turn_intent_accuracy",
    "event_sequence_match",
    "context_retention",
    "response_grounding",
    "resume_success_rate",
    "thread_continuity",
    "side_effect_accuracy",
    "final_task_success",
    "latency_ms",
    "llm_call_count",
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "latency_p95_ms",
    "total_tokens_p95",
)


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def score_case(case: ConversationEvalCase, run: ConversationRunOutput) -> ConversationCaseScore:
    paired = list(zip(case.turns, run.turns))
    complete = len(case.turns) == len(run.turns)
    outcomes = [exact_match(actual.outcome, gold.expected_outcome) for gold, actual in paired]
    intents = [exact_match(actual.intents, gold.expected_intents) for gold, actual in paired]
    events = [
        ordered_subsequence(actual.event_types, gold.expected_event_subsequence)
        for gold, actual in paired
    ]
    context = [
        reference_recall(actual.retained_context_refs, gold.expected_context_refs)
        for gold, actual in paired
    ]
    responses = [
        response_contains(actual.reply_text, gold.expected_response_contains)
        for gold, actual in paired
    ]
    resumes = [
        resume_success(
            actual.kind,
            actual.run_id,
            actual.resumed_from_run_id,
            actual.outcome,
            actual.reached_terminal,
        )
        for _, actual in paired
    ]
    continuity = thread_continuity(
        [turn.thread_id for turn in run.turns],
        case.require_single_thread,
    )
    side_effect = side_effect_accuracy(run.final_note_delta, case.expected_final_note_delta)
    terminal_requirements = [
        (not gold.must_reach_terminal) or actual.reached_terminal
        for gold, actual in paired
    ]
    final_success = 1.0 if (
        complete
        and all(value == 1.0 for value in outcomes + intents + events + context + responses + resumes)
        and all(terminal_requirements)
        and continuity == 1.0
        and side_effect == 1.0
    ) else 0.0
    return ConversationCaseScore(
        case_id=case.id,
        turn_outcome_accuracy=_mean(outcomes) if complete else 0.0,
        turn_intent_accuracy=_mean(intents) if complete else 0.0,
        event_sequence_match=_mean(events) if complete else 0.0,
        context_retention=_mean(context) if complete else 0.0,
        response_grounding=_mean(responses) if complete else 0.0,
        resume_success_rate=_mean(resumes) if complete else 0.0,
        thread_continuity=continuity if complete else 0.0,
        side_effect_accuracy=side_effect,
        final_task_success=final_success,
        latency_ms=run.latency_ms,
        llm_call_count=float(run.llm_call_count),
        input_tokens=float(run.input_tokens),
        output_tokens=float(run.output_tokens),
        total_tokens=float(run.total_tokens),
    )


@dataclass(frozen=True)
class ConversationQualityReport:
    num_cases: int
    means: dict[str, float] = field(default_factory=dict)
    per_case: list[ConversationCaseScore] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"Conversation Quality Report ({self.num_cases} cases)"]
        lines.extend(f"  {name:<26} {self.means.get(name, 0.0):.4f}" for name in _METRIC_NAMES)
        return "\n".join(lines)

    def check_thresholds(self, thresholds: dict[str, float]) -> list[str]:
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


def aggregate(scores: list[ConversationCaseScore]) -> ConversationQualityReport:
    if not scores:
        return ConversationQualityReport(0, dict.fromkeys(_METRIC_NAMES, 0.0))
    base_names = tuple(name for name in _METRIC_NAMES if name not in {
        "latency_p95_ms", "total_tokens_p95",
    })
    means = {
        name: round(sum(getattr(score, name) for score in scores) / len(scores), 4)
        for name in base_names
    }
    means["latency_p95_ms"] = _percentile([s.latency_ms for s in scores], 0.95)
    means["total_tokens_p95"] = _percentile([s.total_tokens for s in scores], 0.95)
    return ConversationQualityReport(len(scores), means, scores)


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * quantile + 0.999999)))
    return round(ordered[index], 4)


def score_all(
    cases: list[ConversationEvalCase],
    runs: dict[str, ConversationRunOutput],
) -> ConversationQualityReport:
    return aggregate([score_case(case, runs[case.id]) for case in cases if case.id in runs])
