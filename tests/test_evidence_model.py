from __future__ import annotations

from types import SimpleNamespace

from personal_agent.agent.ask_pipeline_factory import AskPipelineFactory
from personal_agent.core.candidate_enrichers import ParentChildCandidateEnricher
from personal_agent.core.config import Settings
from personal_agent.core.evidence import (
    EvidenceItem,
    build_context_pack,
    notes_to_evidence,
    rank_evidence_items,
    select_ranked_evidence,
)
from personal_agent.core.rerankers import LlmEvidenceReranker
from personal_agent.core.models import Citation
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

    def test_full_construction(self):
        item = EvidenceItem(
            source_type="graph_fact",
            source_id="edge-1",
            title="Redis",
            snippet="Redis supports caching",
            fact="Redis supports caching mechanisms",
            source_span="p1-3",
            url="https://example.com",
            score=0.85,
            metadata={"orphan": False, "episode_uuids": ["ep-1"]},
        )
        assert item.fact == "Redis supports caching mechanisms"
        assert item.score == 0.85
        assert item.metadata["orphan"] is False

    def test_serialization_roundtrip(self):
        item = EvidenceItem(
            source_type="web",
            source_id="https://example.com",
            title="Example",
            snippet="Test snippet",
            url="https://example.com",
        )
        data = item.model_dump(mode="json")
        restored = EvidenceItem.model_validate(data)
        assert restored.source_type == item.source_type
        assert restored.source_id == item.source_id
        assert restored.title == item.title

    def test_metadata_preserves_arbitrary_keys(self):
        item = EvidenceItem(
            source_type="graph_fact",
            metadata={"custom_key": [1, 2, 3], "nested": {"a": True}},
        )
        assert item.metadata["custom_key"] == [1, 2, 3]
        assert item.metadata["nested"]["a"] is True

    def test_unique_evidence_ids(self):
        items = [EvidenceItem(source_type="note") for _ in range(100)]
        ids = {item.evidence_id for item in items}
        assert len(ids) == 100


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


class TestEvidenceRerankers:
    def test_factory_builds_heuristic_reranker_by_default(self):
        components = AskPipelineFactory(Settings()).create()

        assert components.reranker.name == "heuristic"
        assert components.candidate_enricher.name == "parent_child"
        assert components.context_max_items == 12

    def test_llm_reranker_reorders_candidates(self, monkeypatch):
        settings = Settings(
            planner=Settings().planner.model_copy(update={"api_key": "test-key"}),
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

        monkeypatch.setattr("personal_agent.core.llm_trace.OpenAI", FakeOpenAI)

        pack = LlmEvidenceReranker(settings).rerank(
            "服务降级是什么",
            evidence,
            max_items=2,
            char_budget=1000,
        )

        assert [item.evidence.source_id for item in pack.selected] == ["good", "bad"]
        assert pack.selected[0].reason.startswith("llm_rerank")


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
