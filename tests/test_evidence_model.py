from __future__ import annotations

from types import SimpleNamespace

from personal_agent.application.ask_pipeline_factory import AskPipelineFactory
from personal_agent.application.candidate_enrichers import ParentChildCandidateEnricher
from personal_agent.kernel.config import Settings
from personal_agent.kernel.evidence import (
    Candidate,
    EvidenceItem,
    build_context_pack,
    candidate_from_evidence,
    candidate_to_evidence,
    notes_to_evidence,
    rank_evidence_items,
    select_ranked_evidence,
)
from personal_agent.application.rerankers import LlmEvidenceReranker
from personal_agent.kernel.models import Citation
from tests.note_factory import make_note


class TestEvidenceItem:
    def test_default_values(self):
        item = EvidenceItem(source_type="note", source_id="n1")
        assert item.source_type == "note"
        assert item.source_id == "n1"
        assert item.title == ""
        assert item.snippet == ""
        assert item.fact is None
        assert item.source_span is None
        assert item.url is None
        assert item.score == 0.0
        assert item.metadata == {}
        assert len(item.evidence_id) == 12

    def test_all_source_types(self):
        for st in ("graph_fact", "note", "chunk", "web", "tool", "episode", "procedural", "reflection"):
            item = EvidenceItem(source_type=st)
            assert item.source_type == st

    def test_unique_evidence_ids(self):
        items = [EvidenceItem(source_type="note") for _ in range(100)]
        ids = {item.evidence_id for item in items}
        assert len(ids) == 100


class TestCandidateSchema:
    def test_candidate_roundtrips_from_evidence_metadata(self):
        evidence = EvidenceItem(
            evidence_id="ev0000000001",
            source_type="chunk",
            source_id="chunk-1",
            parent_note_id="doc-1",
            title="Hybrid RAG",
            snippet="Dense and sparse retrieval are fused with RRF.",
            source_span="p2:10-20",
            score=0.72,
            metadata={
                "retrieved_by": "local",
                "source_ranks": {"dense": 3, "sparse": 1},
                "dense_score": 0.81,
                "sparse_score": 7.4,
            },
        )

        candidate = candidate_from_evidence(evidence)
        restored = candidate_to_evidence(candidate)

        assert isinstance(candidate, Candidate)
        assert candidate.candidate_id == "ev0000000001"
        assert candidate.document_id == "doc-1"
        assert candidate.chunk_id == "chunk-1"
        assert candidate.dense_rank == 3
        assert candidate.sparse_rank == 1
        assert candidate.dense_score == 0.81
        assert restored.source_type == "chunk"
        assert restored.source_id == "chunk-1"
        assert restored.metadata["candidate"]["candidate_id"] == candidate.candidate_id


class TestContextPack:
    def test_prefers_relevant_chunk_over_unrelated_web(self):
        evidence = [
            EvidenceItem(
                source_type="web",
                source_id="https://example.com/a",
                title="Unrelated",
                snippet="天气 新闻 股票",
            ),
            EvidenceItem(
                source_type="chunk",
                source_id="c1",
                title="服务降级",
                snippet="服务降级是在系统压力过大时主动关闭非核心能力。",
                source_span="0-20",
            ),
        ]

        pack = build_context_pack("什么是服务降级", evidence)

        assert pack.selected
        assert pack.selected[0].evidence.source_id == "c1"
        assert "term_overlap" in pack.selected[0].reason

    def test_respects_char_budget_and_records_dropped(self):
        evidence = [
            EvidenceItem(
                source_type="chunk",
                source_id=f"c{i}",
                title=f"chunk {i}",
                snippet="服务降级" + ("很长的证据" * 80),
            )
            for i in range(5)
        ]

        pack = build_context_pack("服务降级", evidence, max_items=5, char_budget=300)

        assert pack.selected
        assert pack.dropped
        assert pack.used_chars >= pack.selected[0].estimated_chars
        assert {item.drop_reason for item in pack.dropped} == {"char_budget"}

    def test_rank_and_select_are_separate_steps(self):
        evidence = [
            EvidenceItem(source_type="web", source_id="w1", snippet="unrelated"),
            EvidenceItem(source_type="chunk", source_id="c1", snippet="服务降级 保护核心链路"),
        ]

        ranked = rank_evidence_items("服务降级", evidence)
        pack = select_ranked_evidence("服务降级", ranked, max_items=1, char_budget=500)

        assert ranked[0].evidence.source_id == "c1"
        assert [item.evidence.source_id for item in pack.selected] == ["c1"]

    def test_deprecated_note_evidence_is_not_selected(self):
        note = make_note(
            id="old",
            title="旧部署流程",
            content="部署流程使用 Jenkins。",
            summary="Jenkins",
            version_status="deprecated",
        )

        pack = build_context_pack("部署流程", notes_to_evidence([note]), max_items=3)

        assert pack.selected == []
        assert pack.dropped
        assert pack.dropped[0].evidence.metadata["version_status"] == "deprecated"
        assert pack.dropped[0].drop_reason == "stale_version"

    def test_selects_parent_companion_for_selected_child_when_budget_allows(self):
        evidence = [
            EvidenceItem(
                source_type="chunk",
                source_id="child-1",
                parent_note_id="parent-1",
                title="MRP method",
                snippet="MRP is a planning method for production systems.",
                score=1.0,
            ),
            EvidenceItem(
                source_type="note",
                source_id="parent-1",
                title="Production planning",
                snippet="Parent overview for production planning methods.",
                score=0.1,
            ),
            EvidenceItem(
                source_type="chunk",
                source_id="other",
                title="Other",
                snippet="MRP production planning background from another source.",
                score=0.9,
            ),
        ]

        pack = build_context_pack(
            "Is MRP a planning method for production systems?",
            evidence,
            max_items=3,
            char_budget=1200,
        )

        assert [item.evidence.source_id for item in pack.selected[:2]] == [
            "child-1",
            "parent-1",
        ]
        assert pack.selected[1].reason.startswith("parent_companion")


class TestEvidenceRerankers:
    def test_factory_builds_support_reranker_by_default(self):
        components = AskPipelineFactory(Settings()).create()

        assert components.reranker.name == "support"
        assert components.candidate_enricher.name == "parent_child"
        assert components.context_max_items == 12

    def test_factory_can_build_heuristic_reranker_explicitly(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={"reranker": "heuristic"}),
        )
        components = AskPipelineFactory(settings).create()

        assert components.reranker.name == "heuristic"

    def test_factory_builds_gated_llm_reranker(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={"reranker": "llm_gated"}),
        )
        components = AskPipelineFactory(settings, planner_client=object()).create()

        assert components.reranker.name == "llm_gated"

    def test_llm_reranker_reorders_candidates(self, monkeypatch):
        settings = Settings(
            ask=Settings().ask.model_copy(update={"reranker": "llm", "llm_rerank_top_n": 2}),
        )
        evidence = [
            EvidenceItem(
                evidence_id="bad000000001",
                source_type="chunk",
                source_id="bad",
                snippet="generic architecture note",
            ),
            EvidenceItem(
                evidence_id="good00000001",
                source_type="chunk",
                source_id="good",
                snippet="服务降级 保护核心链路",
            ),
        ]

        class FakeCompletions:
            def create(self, **kwargs):
                assert kwargs["response_format"]["type"] == "json_schema"
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content='{"ranked_ids":["good00000001","bad000000001"]}'
                            )
                        )
                    ]
                )

        class FakeOpenAI:
            def __init__(self, **kwargs):
                assert kwargs["api_key"] == "test-key"
                self.chat = SimpleNamespace(completions=FakeCompletions())

        monkeypatch.setattr("personal_agent.infra.structured_model.OpenAI", FakeOpenAI)

        from personal_agent.infra.structured_model import StrictJsonSchemaAdapter
        from personal_agent.kernel.config_models import StructuredConfig

        client = StrictJsonSchemaAdapter(
            StructuredConfig(api_key="test-key", base_url="https://u.invalid", model="m"),
        )

        pack = LlmEvidenceReranker(settings, model_client=client).rerank(
            "服务降级是什么",
            evidence,
            max_items=2,
            char_budget=1000,
        )

        assert [item.evidence.source_id for item in pack.selected] == ["good", "bad"]
        assert pack.selected[0].reason.startswith("llm_rerank")

    def test_gated_llm_reranker_skips_model_for_high_confidence_top_hit(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={
                "reranker": "llm_gated",
                "llm_rerank_gated_min_candidates": 2,
                "llm_rerank_gated_low_score": 0.1,
            }),
        )
        calls = []

        class FakeClient:
            def generate(self, request):
                calls.append(request)
                return SimpleNamespace(value=SimpleNamespace(ranked_ids=[]))

        evidence = [
            EvidenceItem(
                evidence_id="top000000001",
                source_type="chunk",
                source_id="top",
                title="服务降级",
                snippet="服务降级 服务降级 服务降级 保护核心链路",
                score=1.0,
                metadata={"consensus_count": 2, "source_ranks": {"dense": 1, "sparse": 1}},
            ),
            EvidenceItem(
                evidence_id="weak00000001",
                source_type="web",
                source_id="weak",
                snippet="unrelated weather stock news",
                score=0.0,
            ),
        ]

        pack = AskPipelineFactory(settings, planner_client=FakeClient()).create().reranker.rerank(
            "服务降级是什么",
            evidence,
            max_items=2,
            char_budget=1000,
        )

        assert calls == []
        assert [item.evidence.source_id for item in pack.selected] == ["top", "weak"]
        reranker = AskPipelineFactory(settings, planner_client=FakeClient()).create().reranker
        reranker.rerank("服务降级是什么", evidence, max_items=2, char_budget=1000)
        assert reranker.last_telemetry["triggered"] is False
        assert reranker.last_telemetry["llm_call_count"] == 0

    def test_gated_llm_reranker_triggers_on_close_scores(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={
                "reranker": "llm_gated",
                "llm_rerank_top_n": 2,
                "llm_rerank_gated_min_candidates": 2,
                "llm_rerank_gated_score_margin": 0.2,
            }),
        )
        calls = []

        class FakeClient:
            def generate(self, request):
                calls.append(request)
                return SimpleNamespace(
                    value=SimpleNamespace(ranked_ids=["good00000001", "bad000000001"])
                )

        evidence = [
            EvidenceItem(
                evidence_id="bad000000001",
                source_type="chunk",
                source_id="bad",
                snippet="cache generic architecture note",
                score=0.4,
            ),
            EvidenceItem(
                evidence_id="good00000001",
                source_type="chunk",
                source_id="good",
                snippet="cache protects the core service path during degradation",
                score=0.4,
            ),
        ]

        reranker = AskPipelineFactory(settings, planner_client=FakeClient()).create().reranker
        pack = reranker.rerank(
            "cache",
            evidence,
            max_items=2,
            char_budget=1000,
        )

        assert len(calls) == 1
        assert [item.evidence.source_id for item in pack.selected] == ["good", "bad"]
        assert pack.selected[0].reason.startswith("llm_gated(score_margin)")
        assert reranker.last_telemetry["triggered"] is True
        assert reranker.last_telemetry["trigger_reason"] == "score_margin"
        assert reranker.last_telemetry["llm_call_count"] == 1

    def test_support_reranker_promotes_direct_support_over_background(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={"reranker": "support"}),
        )
        evidence = [
            EvidenceItem(
                evidence_id="bg0000000001",
                source_type="chunk",
                source_id="background",
                title="Architecture background",
                snippet="This section discusses general architecture patterns and deployment history.",
                score=1.0,
            ),
            EvidenceItem(
                evidence_id="direct000001",
                source_type="chunk",
                source_id="direct",
                title="Service degradation",
                snippet=(
                    "Service degradation protects the core service path by disabling "
                    "non-critical features."
                ),
                score=0.2,
                metadata={
                    "consensus_count": 2,
                    "source_ranks": {"dense": 2, "sparse": 1},
                },
            ),
        ]

        reranker = AskPipelineFactory(settings).create().reranker
        pack = reranker.rerank(
            "How does service degradation protect the core service path?",
            evidence,
            max_items=2,
            char_budget=1200,
        )

        assert [item.evidence.source_id for item in pack.selected] == ["direct", "background"]
        assert pack.selected[0].evidence.metadata["support_status"] in {
            "direct_support",
            "strong_support",
        }
        assert reranker.last_telemetry["support_top_status"] in {
            "direct_support",
            "strong_support",
        }

    def test_gated_llm_reranker_triggers_when_top_lacks_direct_support(self):
        settings = Settings(
            ask=Settings().ask.model_copy(update={
                "reranker": "llm_gated",
                "llm_rerank_top_n": 2,
                "llm_rerank_gated_min_candidates": 2,
                "llm_rerank_gated_low_score": 0.0,
                "support_rerank_weight": 0.0,
                "support_rerank_consensus_weight": 0.0,
                "llm_rerank_gated_min_support_coverage": 0.5,
            }),
        )
        calls = []

        class FakeClient:
            def generate(self, request):
                calls.append(request)
                return SimpleNamespace(
                    value=SimpleNamespace(ranked_ids=["direct000001", "bg0000000001"])
                )

        evidence = [
            EvidenceItem(
                evidence_id="bg0000000001",
                source_type="chunk",
                source_id="background",
                title="Architecture background",
                snippet=(
                    "Service degradation core service path overload is discussed "
                    "as general architecture background."
                ),
                score=1.0,
                metadata={"support_status": "background_only", "support_coverage": 0.0},
            ),
            EvidenceItem(
                evidence_id="direct000001",
                source_type="web",
                source_id="direct",
                title="Service degradation",
                snippet=(
                    "Service degradation protects the core service path by disabling "
                    "non-critical features."
                ),
                score=0.2,
            ),
        ]

        reranker = AskPipelineFactory(settings, planner_client=FakeClient()).create().reranker
        pack = reranker.rerank(
            "How does service degradation protect the core service path?",
            evidence,
            max_items=2,
            char_budget=1200,
        )

        assert len(calls) == 1
        assert [item.evidence.source_id for item in pack.selected] == ["direct", "background"]
        assert pack.selected[0].reason.startswith("llm_gated(weak_top_support)")
        assert reranker.last_telemetry["trigger_reason"] == "weak_top_support"
        assert reranker.last_telemetry["support_top_status"] == "background_only"


class TestCandidateEnrichers:
    def test_parent_hit_adds_query_relevant_children(self):
        parent = make_note(
            id="p1",
            user_id="u1",
            title="Atmosphere paper",
            content="abstract about pressure broadening",
            summary="abstract about pressure broadening",
        )
        weak_child = make_note(
            id="c1",
            user_id="u1",
            title="Appendix",
            content="audio codec parameters and calibration",
            summary="audio codec parameters and calibration",
            parent_note_id="p1",
            chunk_index=1,
        )
        strong_child = make_note(
            id="c2",
            user_id="u1",
            title="Precision requirements",
            content="biases on atmospheric inferences decrease with lower perturbation levels on pressure-broadening parameters",
            summary="biases on atmospheric inferences decrease with lower perturbation levels on pressure-broadening parameters",
            parent_note_id="p1",
            chunk_index=2,
        )

        class FakeStore:
            def get_chunks_for_parent(self, parent_note_id):
                assert parent_note_id == "p1"
                return [weak_child, strong_child]

            def get_parent_note(self, note_id):
                return parent

        settings = Settings(
            ask=Settings().ask.model_copy(update={"parent_child_top_n": 1})
        )
        result = ParentChildCandidateEnricher(settings).enrich(
            "Are biases on atmospheric inferences expected to decrease with lower perturbation levels on pressure-broadening parameters?",
            evidence=notes_to_evidence([parent]),
            matches=[parent],
            citations=[Citation(note_id=parent.id, title=parent.body.title, snippet=parent.body.summary)],
            store=FakeStore(),
        )

        assert result.added_note_ids == ["c2"]
        assert [item.source_id for item in result.evidence] == ["p1", "c2"]
        assert [note.id for note in result.matches] == ["p1", "c2"]
