from __future__ import annotations

import pytest

from personal_agent.application.knowledge.answer_verifier import (
    LLMKnowledgeAnswerVerifier,
)
from personal_agent.application.knowledge.models import EvidenceSpan
from personal_agent.capabilities.contracts.model import StructuredModelResponse


class _StructuredResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        return StructuredModelResponse(
            value=request.output_type.model_validate(self.payload),
            model="test-semantic-verifier",
            latency_ms=1,
        )


def _span(span_id: str, text: str) -> EvidenceSpan:
    return EvidenceSpan(
        evidence_span_id=span_id,
        evidence_block_id=f"block-{span_id}",
        text_span=text,
        quote_hash=f"hash-{span_id}",
    )


def test_knowledge_answer_verifier_binds_conflict_to_selected_evidence() -> None:
    model = _StructuredResponse({
        "verdict": "needs_revision",
        "conclusion_status": "conflicted",
        "evidence_coverage": "complete",
        "conflicts": [{
            "evidence_span_ids": ["span-a", "span-b"],
            "description": "The selected dates are incompatible.",
        }],
        "feedback": "State the unresolved conflict explicitly.",
        "confidence": 0.97,
    })
    verifier = LLMKnowledgeAnswerVerifier(model)
    selected = [
        _span("span-a", "Northstar 的迁移日期是 2026-09-10。"),
        _span("span-b", "Northstar 的迁移日期是 2026-10-15。"),
    ]

    assessment = verifier.verify(
        question="核对 Northstar 的迁移日期并明确冲突。",
        candidate_answer="\n".join(item.text_span for item in selected),
        selected=selected,
        available=selected,
        manifests=[],
    )

    assert assessment.verdict == "needs_revision"
    assert assessment.conclusion_status == "conflicted"
    assert assessment.conflicts[0].evidence_span_ids == ["span-a", "span-b"]
    assert assessment.verifier_name == "llm-knowledge-answer-verifier"
    assert model.requests[0].operation == "knowledge_answer_semantic_verification"


def test_knowledge_answer_verifier_rejects_unknown_evidence_reference() -> None:
    model = _StructuredResponse({
        "verdict": "needs_revision",
        "conclusion_status": "conflicted",
        "conflicts": [{
            "evidence_span_ids": ["span-a", "invented-span"],
            "description": "An invented conflict binding.",
        }],
    })
    verifier = LLMKnowledgeAnswerVerifier(model)
    selected = [_span("span-a", "Northstar 的迁移日期是 2026-09-10。")]

    with pytest.raises(
        ValueError,
        match="outside the selected set",
    ):
        verifier.verify(
            question="核对 Northstar 的迁移日期。",
            candidate_answer=selected[0].text_span,
            selected=selected,
            available=selected,
            manifests=[],
        )
