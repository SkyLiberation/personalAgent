from __future__ import annotations

from personal_agent.application.candidate_fusion import CandidateFusion
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


def test_candidate_fusion_rewards_multi_source_consensus():
    consensus = EvidenceItem(
        source_type="chunk",
        source_id="n1",
        snippet="Hybrid RAG combines dense semantic and sparse lexical recall.",
        metadata={"source_ranks": {"dense": 5, "sparse": 2}},
    )
    dense_only = EvidenceItem(
        source_type="chunk",
        source_id="n2",
        snippet="Dense retrieval can find semantically similar passages.",
        metadata={"source_ranks": {"dense": 1}},
    )

    result = CandidateFusion().fuse_evidence([dense_only, consensus])

    assert [item.source_id for item in result.evidence] == ["n1", "n2"]
    assert result.evidence[0].metadata["fusion_rank"] == 1
    assert result.evidence[0].metadata["consensus_count"] == 2
    assert {c["source"] for c in result.evidence[0].metadata["fusion_components"]} == {
        "dense",
        "sparse",
    }


def test_assemble_context_uses_candidate_fusion_trace():
    engine = EvidenceEngine()
    evidence = [
        EvidenceItem(
            source_type="chunk",
            source_id="n1",
            title="RRF",
            snippet="RRF rewards candidates found by dense and sparse retrievers.",
            metadata={"source_ranks": {"dense": 3, "sparse": 2}},
        ),
        EvidenceItem(
            source_type="chunk",
            source_id="n2",
            title="Background",
            snippet="General background.",
            metadata={"source_ranks": {"dense": 1}},
        ),
    ]

    result = engine.assemble_context(EvidenceAssemblyRequest(
        question="How does RRF reward dense and sparse agreement?",
        evidence=evidence,
        matches=[],
        citations=[],
        store=object(),
        filters=None,
        candidate_enricher=NoopCandidateEnricher(),
        reranker=HeuristicEvidenceReranker(),
        max_items=2,
        char_budget=800,
        policy=EvidenceAssemblyPolicy(max_evidence_items=2, max_context_chars=800),
    ))

    assert result.assembly_trace.after_dedupe_count == 2
    assert result.assembly_trace.after_fusion_count == 2
    assert any(line.startswith("CandidateFusion(") for line in result.trace)


def test_assemble_context_records_reranker_telemetry():
    class TelemetryReranker(HeuristicEvidenceReranker):
        name = "telemetry"

        def rerank(self, *args, **kwargs):
            self.last_telemetry = {
                "triggered": True,
                "trigger_reason": "score_margin",
                "llm_call_count": 1,
                "fallback_reason": "",
                "candidate_count": 2,
            }
            return super().rerank(*args, **kwargs)

    engine = EvidenceEngine()
    result = engine.assemble_context(EvidenceAssemblyRequest(
        question="hybrid retrieval",
        evidence=[
            EvidenceItem(source_type="chunk", source_id="n1", snippet="hybrid retrieval"),
            EvidenceItem(source_type="chunk", source_id="n2", snippet="retrieval background"),
        ],
        matches=[],
        citations=[],
        store=object(),
        filters=None,
        candidate_enricher=NoopCandidateEnricher(),
        reranker=TelemetryReranker(),
        max_items=2,
        char_budget=800,
        policy=EvidenceAssemblyPolicy(max_evidence_items=2, max_context_chars=800),
    ))

    assert any(
        line.startswith("RerankerTelemetry(telemetry):")
        and "reason=score_margin" in line
        and "llm_calls=1" in line
        for line in result.trace
    )


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
