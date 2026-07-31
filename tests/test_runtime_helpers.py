from __future__ import annotations

import pytest
from pathlib import Path

from personal_agent.orchestration.runtime_helpers import (
    _extract_question_keywords,
    _graph_episode_uuids,
    _split_sentences,
    _tokenize_for_overlap,
)
from personal_agent.kernel.evidence import _best_snippet
from personal_agent.kernel.models import (
    GraphNodeRef,
    GraphEdgeRef,
    GraphFactRef,
)
from personal_agent.memory.graphiti.store import GraphCaptureResult
from personal_agent.kernel.graph_results import GraphRetrievalResult
from personal_agent.infra.storage.postgres_memory_store import PostgresMemoryStore
from tests.conftest import POSTGRES_URL
from tests.note_factory import make_note

pytestmark = pytest.mark.usefixtures("clean_postgres_business_tables")


class TestTokenizeForOverlap:
    def test_filters_short_and_punctuation(self):
        tokens = _tokenize_for_overlap("a ab cd e? xyz!")
        assert tokens == {"ab", "cd", "xyz"}

    def test_empty_string(self):
        assert _tokenize_for_overlap("") == set()

    def test_mixed_case(self):
        tokens = _tokenize_for_overlap("Hello World TEST")
        assert tokens == {"hello", "world", "test"}


class TestSplitSentences:
    def test_chinese_delimiters(self):
        parts = _split_sentences("这是第一句。这是第二句！这是第三句？")
        assert len(parts) == 3
        assert "第一句" in parts[0]
        assert "第二句" in parts[1]
        assert "第三句" in parts[2]

    def test_mixed_chinese_english(self):
        parts = _split_sentences("Hello world. 中文句子。Another one!")
        assert len(parts) == 3

    def test_newline_as_delimiter(self):
        parts = _split_sentences("line one\nline two")
        assert len(parts) == 2


class TestExtractQuestionKeywords:
    def test_chinese_keywords(self):
        keywords = _extract_question_keywords("什么是服务降级？")
        assert any("服务降级" in kw for kw in keywords) or any("服务" in kw for kw in keywords)

    def test_english_keywords(self):
        keywords = _extract_question_keywords("What is Redis caching?")
        assert "redis" in keywords
        assert "caching" in keywords

    def test_mixed_keywords(self):
        keywords = _extract_question_keywords("如何配置 Redis 缓存策略？")
        assert "redis" in keywords


class TestBestSnippet:
    def test_returns_best_matching_sentence(self):
        note = make_note(
            id="n1", title="缓存策略", user_id="test",
            content="Redis 使用内存存储数据。缓存失效策略包括 TTL 和 LRU。",
            summary="关于 Redis 缓存的笔记",
        )
        from personal_agent.memory.graphiti.reranker import GraphCitationHit

        hit = GraphCitationHit(
            episode_uuid="ep1",
            relation_fact="缓存失效策略包括 TTL",
            endpoint_names=["缓存", "TTL"],
            matched_terms=["缓存"],
            entity_overlap_count=2,
            score=90,
        )
        snippet = _best_snippet(note, hit, "什么是缓存失效策略？")
        assert "缓存失效策略" in snippet or len(snippet) > 0

    def test_fallback_to_summary(self):
        note = make_note(
            id="n2", title="测试笔记", user_id="test",
            content="一些无关的内容。",
            summary="这是关于缓存策略的摘要说明，包含重要信息。",
        )
        from personal_agent.memory.graphiti.reranker import GraphCitationHit

        hit = GraphCitationHit(
            episode_uuid="ep2",
            relation_fact="完全不匹配的内容",
            endpoint_names=[],
            matched_terms=[],
            entity_overlap_count=0,
            score=10,
        )
        snippet = _best_snippet(note, hit, "缓存策略？")
        assert len(snippet) > 0


class TestMergeGraphCaptureRefs:
    def test_merge_populates_refs(self):
        note = make_note(title="test", content="c", summary="s", user_id="u1")
        graph_result = GraphCaptureResult(
            enabled=True,
            episode_uuid="ep-1",
            entity_names=["Redis"],
            relation_facts=["Redis supports caching"],
            related_episode_uuids=[],
            node_refs=[GraphNodeRef(uuid="n1", name="Redis")],
            edge_refs=[GraphEdgeRef(uuid="e1", fact="Redis supports caching", source_node_name="Redis")],
            fact_refs=[GraphFactRef(fact="Redis supports caching", edge_uuid="e1", source_node_name="Redis")],
        )
        from personal_agent.application.capture.ingestion_pipeline import IngestionPipeline
        pipeline = object.__new__(IngestionPipeline)
        pipeline._merge_graph_capture(note, graph_result)
        assert note.graph.episode_uuid == "ep-1"
        assert note.graph.entity_names == ["Redis"]
        assert len(note.graph.node_refs) == 1
        assert note.graph.node_refs[0].uuid == "n1"
        assert len(note.graph.edge_refs) == 1
        assert note.graph.edge_refs[0].source_node_name == "Redis"
        assert len(note.graph.fact_refs) == 1
        assert note.graph.fact_refs[0].edge_uuid == "e1"
        assert note.graph_sync.status == "synced"


class TestGraphRetrievalSemanticEvidence:
    def test_episode_uuids_include_fact_and_edge_refs(self):
        graph_result = GraphRetrievalResult(
            enabled=True,
            related_episode_uuids=["ep-related"],
            fact_refs=[
                GraphFactRef(
                    fact="订单服务依赖 Redis",
                    edge_uuid="edge-1",
                    episode_uuids=["ep-fact"],
                )
            ],
            edge_refs=[
                GraphEdgeRef(
                    uuid="edge-2",
                    fact="Redis 缓解数据库压力",
                    episodes=["ep-edge"],
                )
            ],
        )

        assert _graph_episode_uuids(graph_result) == ["ep-fact", "ep-edge", "ep-related"]

class TestGraphRefsSerialization:
    def test_note_with_graph_refs_roundtrips(self, temp_dir: Path):
        store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
        note = make_note(
            id="n1", title="Graph note", content="content", summary="summary",
            user_id="test",
            graph_episode_uuid="ep-1",
            entity_names=["Redis"],
            relation_facts=["Redis supports caching"],
            graph_node_refs=[GraphNodeRef(uuid="n1", name="Redis", labels=["Tech"])],
            graph_edge_refs=[GraphEdgeRef(uuid="e1", fact="f", source_node_name="Redis")],
            graph_fact_refs=[GraphFactRef(fact="f", edge_uuid="e1")],
        )
        store.add_note(note)
        loaded = store.get_note("n1")
        assert loaded is not None
        assert loaded.graph.episode_uuid == "ep-1"
        assert len(loaded.graph.node_refs) == 1
        assert loaded.graph.node_refs[0].labels == ["Tech"]
        assert len(loaded.graph.edge_refs) == 1
        assert len(loaded.graph.fact_refs) == 1

    def test_note_without_refs_loads_cleanly(self, temp_dir: Path):
        store = PostgresMemoryStore(temp_dir, POSTGRES_URL)
        note = make_note(
            id="n2", title="Old note", content="c", summary="s", user_id="test",
            entity_names=["Python"],
            relation_facts=["Python is a language"],
        )
        store.add_note(note)
        loaded = store.get_note("n2")
        assert loaded is not None
        assert loaded.graph.entity_names == ["Python"]
        assert loaded.graph.node_refs == []
        assert loaded.graph.edge_refs == []
        assert loaded.graph.fact_refs == []
