from __future__ import annotations

from personal_agent.application.candidate_enrichers import NoopCandidateEnricher
from personal_agent.application.evidence_engine import (
    EvidenceAssemblyPolicy,
    EvidenceAssemblyRequest,
    EvidenceEngine,
)
from personal_agent.application.rerankers import HeuristicEvidenceReranker
from personal_agent.kernel.evidence import EvidenceItem, SourceDocument


def test_assemble_context_selects_evidence_and_traces_steps():
    engine = EvidenceEngine()
    evidence = [
        EvidenceItem(source_type="note", source_id="n1", title="Redis", snippet="Redis 缓存能降低数据库负载。"),
        EvidenceItem(source_type="note", source_id="n2", title="Other", snippet="无关内容。"),
    ]

    result = engine.assemble_context(EvidenceAssemblyRequest(
        question="Redis 缓存如何降低负载？",
        evidence=evidence,
        matches=[],
        citations=[],
        store=object(),
        filters=None,
        candidate_enricher=NoopCandidateEnricher(),
        reranker=HeuristicEvidenceReranker(),
        max_items=1,
        char_budget=500,
        policy=EvidenceAssemblyPolicy(max_evidence_items=1, max_context_chars=500),
    ))

    assert len(result.context_pack.selected) == 1
    assert result.context_pack.evidence[0].source_id == "n1"
    assert result.assembly_trace.input_evidence_count == 2
    assert result.assembly_trace.selected_count == 1
    assert any(line.startswith("ContextPack(") for line in result.trace)


def test_sources_to_evidence_normalizes_source_documents():
    engine = EvidenceEngine()

    evidence = engine.sources_to_evidence([
        SourceDocument(
            source_id="source-1",
            source_type="official",
            source_ref="https://example.com/a",
            canonical_url="https://example.com/a",
            url="https://example.com/a?utm_source=x",
            title="Official update",
            snippet="The product shipped durable workflow support.",
            provider="web_search",
        )
    ])

    assert evidence[0].source_type == "web"
    assert evidence[0].source_id == "source-1"
    assert evidence[0].source_ref == "https://example.com/a"
    assert evidence[0].metadata["source_document_type"] == "official"


def test_verify_claims_uses_shared_evidence_spans():
    engine = EvidenceEngine()
    evidence = [
        EvidenceItem(
            source_type="web",
            source_id="source-1",
            title="Official update",
            snippet="OpenAI released a new agent model for tool use.",
        )
    ]

    checks = engine.verify_claims("OpenAI released a new agent model for tool use.", evidence)

    assert checks[0].status == "supported"
    assert checks[0].supporting_evidence_ids == ["source-1"]
    assert checks[0].spans[0].evidence_id == "source-1"
    assert checks[0].grounding_trace is not None
    assert checks[0].grounding_trace.supported_count == 1


def test_verify_claims_marks_partial_support():
    engine = EvidenceEngine()
    evidence = [
        EvidenceItem(
            source_type="web",
            source_id="source-1",
            title="SDK update",
            snippet="The company released a new SDK for workflow automation.",
        )
    ]

    checks = engine.verify_claims(
        "The company released a new SDK with a 10x latency improvement and industry first benchmark certification.",
        evidence,
    )

    assert checks[0].status == "partially_supported"
    assert checks[0].evidence_spans
    assert checks[0].grounding_trace is not None
    assert checks[0].grounding_trace.partially_supported_count == 1
