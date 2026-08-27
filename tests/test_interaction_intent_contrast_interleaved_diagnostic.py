from __future__ import annotations

from evals.provider_diagnostics.interaction_intent_contrast_interleaved_001 import (
    compare,
)
from personal_agent.application.conversation.interaction_intent import (
    InteractionIntentProposal,
)
from personal_agent.capabilities.contracts.model import StructuredModelResponse


class _AlternatingResponses:
    def __init__(self) -> None:
        self.calls = 0
        self.requests = []

    def generate(self, request):
        self.calls += 1
        self.requests.append(request)
        is_contrast = "Boundary examples:" in request.messages[0]["content"]
        proposal = (
            InteractionIntentProposal()
            if is_contrast
            else InteractionIntentProposal(
                background_continuation_requested=True,
                background_source_span="独立的外部研究助手",
            )
        )
        return StructuredModelResponse(
            value=proposal,
            model="diagnostic-model",
            latency_ms=20 if is_contrast else 10,
            input_tokens=110 if is_contrast else 100,
            output_tokens=20,
            total_tokens=130 if is_contrast else 120,
        )


def test_interleaved_diagnostic_keeps_arm_counts_and_pair_deltas():
    provider = _AlternatingResponses()
    report = compare(
        provider,
        request_text="请委托一个独立的外部研究助手查阅资料，再由你给出结论。",
        pairs=2,
        config_cohort={"model": "diagnostic-model"},
    )

    assert report["provider_errors"] == []
    assert report["summary"]["control"][
        "misclassified_as_background_count"
    ] == 2
    assert report["summary"]["contrast"][
        "misclassified_as_background_count"
    ] == 0
    assert report["summary"]["control"]["sample_count"] == 2
    assert report["summary"]["contrast"]["sample_count"] == 2
    assert report["summary"]["control"]["total_tokens"] == 240
    assert report["summary"]["contrast"]["total_tokens"] == 260
    assert [row["arm"] for row in report["samples"]] == [
        "control",
        "contrast",
        "contrast",
        "control",
    ]
    for request in provider.requests:
        assert request.operation == "interaction_intent"
        assert request.version == "v2"
        assert request.temperature == 0
        assert request.max_tokens == 800
        assert request.metadata == {
            "component": "interaction_intent_contrast_interleaved_diagnostic"
        }
