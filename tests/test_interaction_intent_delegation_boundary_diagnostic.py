from __future__ import annotations

from hashlib import sha256

from evals.provider_diagnostics.interaction_intent_delegation_boundary_001 import (
    diagnose,
    write_sealed_report,
)
from personal_agent.application.conversation.interaction_intent import (
    InteractionIntentProposal,
)
from personal_agent.capabilities.contracts.model import StructuredModelResponse


class _IntentResponses:
    def __init__(self, *proposals: InteractionIntentProposal) -> None:
        self._proposals = list(proposals)

    def generate(self, request):
        assert request.operation == "interaction_intent"
        return StructuredModelResponse(
            value=self._proposals.pop(0),
            model="diagnostic-model",
            latency_ms=12,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
        )


def test_diagnostic_reports_admitted_background_false_positives(tmp_path):
    foreground = "请委托一个独立的外部研究助手查阅资料，再由你给出结论。"
    ordinary = "请查阅资料并直接给出结论。"
    report = diagnose(
        _IntentResponses(
            InteractionIntentProposal(
                background_continuation_requested=True,
                background_source_span="独立的外部研究助手",
            ),
            InteractionIntentProposal(),
        ),
        requests=((1, foreground), (2, ordinary)),
        config_cohort={"model": "diagnostic-model"},
    )

    assert report["summary"] == {
        "sample_count": 2,
        "misclassified_as_background_count": 1,
        "misclassified_repetitions": [1],
        "provider_error_count": 0,
        "provider_error_repetitions": [],
        "model_call_count": 2,
        "input_tokens": 200,
        "output_tokens": 40,
        "total_tokens": 240,
    }
    assert report["samples"][0]["admitted"][
        "background_continuation_requested"
    ] is True
    assert report["samples"][1]["misclassified_as_background"] is False

    output = tmp_path / "report.json"
    checksum_path = write_sealed_report(report, output)
    expected = sha256(output.read_bytes()).hexdigest()
    assert checksum_path.read_text(encoding="utf-8") == (
        f"{expected} *report.json\n"
    )
